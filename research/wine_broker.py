# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
"""Loopback-only binary HTTP broker for the experimental EVO Wine adapter.

Live sysfs supplies USB metadata; read_control supplies actual whitelisted USB
IN replies. No OUT/SET requests, driver detachment, firmware calls, simulator,
automatic privilege changes, or stored hardware fixtures are available here.
"""

import argparse
import errno
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import struct
import threading

from .devices import (DescriptorError, DeviceSnapshot, SYSFS_USB_ROOT,
                      UnsupportedDevice, enumerate_devices, read_device)
from .protocol import CUR, ControlRead, MAX_DATA_LENGTH
from .readonly import DEVICE_NODE, read_control


SUCCESS = 0x00000000
INTERNAL_ERROR = 0xEE000002
TIMEOUT = 0xEE000003
NO_DEVICES = 0xEE000023
NOT_SUPPORTED = 0xEE000030
NOT_OPENED = 0xEE000033
INVALID_PARAMETER = 0xEE000041
INVALID_INDEX = 0xEE000047
INVALID_DESCRIPTOR = 0xEE000050
UNEXPECTED_DEVICE_RESPONSE = 0xEE000064
ENUM_REQUIRED = 0xEE000070
BUFFER_TOO_SMALL = 0xEE000074

LOOPBACK_ADDRESS = "127.0.0.1"
DEFAULT_PORT = 17690
MAX_ROUTE_LENGTH = 512


class BrokerError(Exception):
    def __init__(self, status: int):
        self.status = status
        # Never format device data or OS exception paths into public errors.
        super().__init__(f"broker status 0x{status:08x}")


def status_from_exception(exc: Exception) -> int:
    """Map failures to statuses confirmed in the original driver DLL."""
    if isinstance(exc, BrokerError):
        return exc.status
    if isinstance(exc, DescriptorError):
        return INVALID_DESCRIPTOR
    if isinstance(exc, UnsupportedDevice):
        return NOT_SUPPORTED
    if isinstance(exc, OSError):
        return {
            errno.ENODEV: NO_DEVICES,
            errno.ENOENT: NOT_OPENED,
            errno.EACCES: NOT_OPENED,
            errno.EPERM: NOT_OPENED,
            errno.EBUSY: NOT_OPENED,
            errno.ETIMEDOUT: TIMEOUT,
            errno.EOPNOTSUPP: NOT_SUPPORTED,
            errno.EPIPE: NOT_SUPPORTED,
        }.get(exc.errno, INTERNAL_ERROR)
    if isinstance(exc, (ValueError, TypeError, UnicodeError)):
        return INVALID_PARAMETER
    return INTERNAL_ERROR


def _argument(text: str, maximum: int = 0xFFFFFFFF) -> int:
    if not re.fullmatch(r"[0-9]{1,10}", text):
        raise BrokerError(INVALID_PARAMETER)
    value = int(text)
    if value > maximum:
        raise BrokerError(INVALID_PARAMETER)
    return value


class BrokerState:
    """An enumeration snapshot with indexes private to this broker process."""

    def __init__(self, sysfs_root: Path = SYSFS_USB_ROOT, node: str = DEVICE_NODE):
        self.sysfs_root = Path(sysfs_root)
        self.node = node
        self._devices: tuple[DeviceSnapshot, ...] | None = None
        self._lock = threading.RLock()

    def health(self) -> bytes:
        with self._lock:
            report = {
                "schema_version": 1,
                "target": {"vendor_id": "2708", "product_id": "000a"},
                "enumerated": self._devices is not None,
                "device_count": len(self._devices) if self._devices is not None else None,
                "bridge_node_present": os.path.exists(self.node),
                "bridge_node_readable": os.access(self.node, os.R_OK),
                "read_only": True,
            }
        return json.dumps(report, separators=(",", ":")).encode("utf-8")

    def _current_device(self, index: int) -> DeviceSnapshot:
        if self._devices is None:
            raise BrokerError(ENUM_REQUIRED)
        if index >= len(self._devices):
            raise BrokerError(INVALID_INDEX)
        original = self._devices[index]
        try:
            current = read_device(original.path)
        except FileNotFoundError:
            raise BrokerError(NO_DEVICES) from None
        if not original.same_connection(current):
            raise BrokerError(ENUM_REQUIRED)
        return current

    def binary_response(self, path: str) -> bytes:
        """Status DWORD plus actual response payload; failures carry status only."""
        try:
            with self._lock:
                payload = self._dispatch(path)
            return struct.pack("<I", SUCCESS) + payload
        except Exception as exc:
            return struct.pack("<I", status_from_exception(exc))

    def _dispatch(self, path: str) -> bytes:
        if len(path) > MAX_ROUTE_LENGTH or "?" in path or "#" in path:
            raise BrokerError(INVALID_PARAMETER)
        fields = path.split("/")
        if fields == ["", "v1", "enumerate"]:
            # A failed refresh invalidates the old snapshot instead of retaining
            # potentially stale indexes. Successful count zero is actual absence.
            self._devices = None
            devices = enumerate_devices(self.sysfs_root)
            self._devices = devices
            return struct.pack("<I", len(devices))
        if len(fields) < 4 or fields[:2] != ["", "v1"]:
            raise BrokerError(NOT_SUPPORTED)
        operation = fields[2]
        expected_fields = {
            "properties": 4, "config": 4, "instance": 4, "instance-id": 4,
            "sample-rate": 4, "read": 11, "string": 6,
        }.get(operation)
        if expected_fields is None:
            raise BrokerError(NOT_SUPPORTED)
        if len(fields) != expected_fields:
            raise BrokerError(INVALID_PARAMETER)
        numbers = [_argument(value) for value in fields[3:]]
        index = numbers[0]
        # Validate the control whitelist even when no device has been enumerated;
        # the route must never permit a SET or an arbitrary extension-unit call.
        if operation == "read":
            _, unit, request, selector, channel, length, timeout = numbers
            preliminary = ControlRead(unit, selector, channel, request, length,
                                      timeout_ms=timeout)
        elif operation == "string":
            _, string_index, langid = numbers
            if string_index > 255 or langid > 65535:
                raise BrokerError(INVALID_PARAMETER)
        device = self._current_device(index)
        if operation == "properties":
            return device.properties()
        if operation == "config":
            return device.configuration
        if operation in ("instance", "instance-id"):
            payload = device.instance_identity()
            if len(payload) > MAX_DATA_LENGTH:
                raise BrokerError(BUFFER_TOO_SMALL)
            return payload
        if operation == "string":
            # Sysfs caches strings without a language ID. This broker cannot
            # claim a genuine GET_DESCRIPTOR response in the requested language.
            # In particular, no "Analogue N" channel labels are synthesized.
            raise BrokerError(NOT_SUPPORTED)
        if operation == "read":
            control = ControlRead(preliminary.unit_id, preliminary.selector,
                                  preliminary.channel, preliminary.request,
                                  preliminary.length, device.interface_number,
                                  preliminary.timeout_ms)
            payload = read_control(device.bus_number, device.device_number,
                                   control, node=self.node)
            if not isinstance(payload, bytes) or len(payload) > control.length:
                raise BrokerError(UNEXPECTED_DEVICE_RESPONSE)
            return payload
        if operation == "sample-rate":
            pin = read_control(device.bus_number, device.device_number,
                               ControlRead(40, 1, 0, CUR, 1, device.interface_number),
                               node=self.node)
            if pin not in (b"\x01", b"\x02", b"\x03"):
                raise BrokerError(UNEXPECTED_DEVICE_RESPONSE)
            source = {1: 41, 2: 44, 3: 45}[pin[0]]
            frequency = read_control(
                device.bus_number, device.device_number,
                ControlRead(source, 1, 0, CUR, 4, device.interface_number),
                node=self.node)
            if not isinstance(frequency, bytes) or len(frequency) != 4:
                raise BrokerError(UNEXPECTED_DEVICE_RESPONSE)
            return frequency
        raise BrokerError(NOT_SUPPORTED)


class BrokerServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port: int = DEFAULT_PORT, *, state: BrokerState | None = None):
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        self.broker_state = state if state is not None else BrokerState()
        super().__init__((LOOPBACK_ADDRESS, port), BrokerHandler)


class BrokerHandler(BaseHTTPRequestHandler):
    # Close each connection. Request bodies and state-changing HTTP methods are
    # never accepted; the only hardware operations are whitelisted USB reads.
    protocol_version = "HTTP/1.0"

    def log_message(self, format, *args):
        pass  # Suppress per-request logging; never log binary data or serials.

    def _reply(self, data: bytes, content_type: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self) -> None:
        # Do not enable CORS. Refuse foreign browser origins/hosts even though
        # the socket itself is restricted to IPv4 loopback.
        host = self.headers.get("Host", "")
        expected_host = f"{LOOPBACK_ADDRESS}:{self.server.server_port}"
        if host not in (LOOPBACK_ADDRESS, expected_host) or self.headers.get("Origin"):
            self._reply(struct.pack("<I", INVALID_PARAMETER), "application/octet-stream", 403)
            return
        if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Length", "0") != "0":
            self._reply(struct.pack("<I", INVALID_PARAMETER), "application/octet-stream", 400)
            return
        if self.path == "/health":
            self._reply(self.server.broker_state.health(), "application/json")
        else:
            self._reply(self.server.broker_state.binary_response(self.path),
                        "application/octet-stream")

    def _unsupported_method(self) -> None:
        self._reply(struct.pack("<I", NOT_SUPPORTED), "application/octet-stream", 405)

    do_POST = _unsupported_method
    do_PUT = _unsupported_method
    do_DELETE = _unsupported_method
    do_PATCH = _unsupported_method
    do_OPTIONS = _unsupported_method
    do_HEAD = _unsupported_method


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Ponte local de leitura EVO 16 para Wine.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port deve estar entre 1 e 65535")
    with BrokerServer(args.port) as server:
        print(f"Ponte somente de leitura em http://127.0.0.1:{args.port}; Ctrl+C para encerrar.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

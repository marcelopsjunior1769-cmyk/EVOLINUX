/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
#ifndef EVO16_BRIDGE_UAPI_H
#define EVO16_BRIDGE_UAPI_H

#include <linux/ioctl.h>
#include <linux/types.h>

#define EVO16_USB_VENDOR_ID 0x2708
#define EVO16_USB_PRODUCT_ID 0x000a
#define EVO16_READONLY_MAX_DATA 4096
#define EVO16_READONLY_NODE "/dev/evo16-readonly"

/*
 * Fixed layout, without pointers, shared by 32-bit and 64-bit processes.
 * Native host byte order applies to integer fields; USB payload is unchanged.
 * actual_length and data are outputs. The kernel discards their input values.
 */
struct evo16_readonly_request {
	__u32 bus_number;
	__u32 device_number;
	__u8 unit_id;
	__u8 selector;
	__u8 channel;
	__u8 request;
	__u16 length;
	__u16 interface_number;
	__u32 timeout_ms;
	__u32 actual_length;
	__u8 data[EVO16_READONLY_MAX_DATA];
};

#define EVO16_READONLY_IOCTL \
	_IOWR(0xe6, 1, struct evo16_readonly_request)

#endif

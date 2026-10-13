# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
"""Installer tests use disposable homes and fake Python/pip; never ALSA or USB."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


INSTALLER = Path(__file__).resolve().parents[1] / "tools" / "install-ubuntu.sh"


class InstallerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.home = self.root / "home with spaces"
        self.home.mkdir()
        self.data = self.home / "share"
        self.source = self.root / "local source with spaces"
        (self.source / "tools").mkdir(parents=True)
        (self.source / "src" / "evolinux").mkdir(parents=True)
        (self.source / "LICENSES").mkdir()
        (self.source / "third_party_licenses").mkdir()
        for name in ("pyproject.toml", "README.md", "LICENSE"):
            (self.source / name).write_text("fixture\n")
        (self.source / "src" / "evolinux" / "cli.py").write_text("# fixture\n")
        (self.source / "src" / "evolinux" / "Audient.dll").write_bytes(b"must not copy")
        self.script = self.source / "tools" / INSTALLER.name
        shutil.copyfile(INSTALLER, self.script)
        self.fake_bin = self.root / "fake-bin"
        self.fake_bin.mkdir()
        self.log = self.root / "commands.jsonl"
        self.env = dict(os.environ,
                        PATH=str(self.fake_bin) + os.pathsep + os.environ["PATH"],
                        INSTALLER_TEST_LOG=str(self.log))
        fake_python = self.fake_bin / "python3"
        fake_python.write_text(
            "#!" + sys.executable + "\n" + r'''
import json
import os
from pathlib import Path
import subprocess
import sys

def log(kind, args):
    with open(os.environ["INSTALLER_TEST_LOG"], "a") as stream:
        stream.write(json.dumps([kind, args]) + "\n")

args = sys.argv[1:]
if args and args[0] == "-c":
    text = args[1]
    log("check", args)
    absent = os.environ.get("INSTALLER_TEST_MISSING", "")
    markers = {"tkinter": "import tkinter", "venv": "import venv", "asound": "ctypes.CDLL", "python": "sys.version_info"}
    raise SystemExit(1 if absent and markers[absent] in text else 0)
if len(args) >= 3 and args[:2] == ["-m", "venv"]:
    destination = Path(args[2])
    bin_directory = destination / "bin"
    bin_directory.mkdir(parents=True)
    log("venv", args)
    python = bin_directory / "python"
    python.write_text("#!" + sys.executable + "\n" + """
import json, os, sys
from pathlib import Path
with open(os.environ['INSTALLER_TEST_LOG'], 'a') as stream:
    stream.write(json.dumps(['pip', sys.argv[1:]]) + '\\n')
source = Path(sys.argv[-1])
if (source / 'src/evolinux/Audient.dll').exists():
    raise SystemExit('proprietary fixture was copied')
raise SystemExit(9 if os.environ.get('INSTALLER_TEST_PIP_FAIL') else 0)
""")
    python.chmod(0o755)
    command = bin_directory / "evolinux"
    command.write_text("#!" + sys.executable + "\n" + """
import json, os, sys
with open(os.environ['INSTALLER_TEST_LOG'], 'a') as stream:
    stream.write(json.dumps(['runtime', sys.argv[1:]]) + '\\n')
raise SystemExit(8 if os.environ.get('INSTALLER_TEST_HELP_FAIL') else 0)
""")
    command.chmod(0o755)
    raise SystemExit(0)
result = subprocess.call(["REAL_PYTHON"] + args)
# Simulate a helper termination AFTER its atomic launcher replacement. This
# checks the shell's cleanup boundary, not a fake failure before activation.
if result == 0 and os.environ.get("INSTALLER_TEST_ACTIVATION_FAIL") and len(args) == 3 and args[0] == "-" and args[-1].endswith("/bin/evolinux"):
    log("post-activation-failure", args)
    result = 42
raise SystemExit(result)
'''.replace('"REAL_PYTHON"', repr(sys.executable))
        )
        fake_python.chmod(0o755)
        for forbidden in ("sudo", "apt", "apt-get", "modprobe", "insmod", "systemctl"):
            path = self.fake_bin / forbidden
            path.write_text("#!/bin/sh\nexit 99\n")
            path.chmod(0o755)

    @property
    def launcher(self):
        return self.home / "bin" / "evolinux"

    @property
    def releases(self):
        location = self.data / "evolinux" / "releases"
        return sorted(location.glob("install-*")) if location.exists() else []

    def run_script(self, *args):
        return subprocess.run(["bash", str(self.script), "--prefix", str(self.home), *args], env=self.env,
                              text=True, capture_output=True, timeout=20)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_check_never_creates_installation_or_invokes_runtime(self):
        result = self.run_script("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertFalse(self.data.exists())
        self.assertTrue(self.commands())
        self.assertTrue(all(kind == "check" for kind, _ in self.commands()))

    def test_missing_prerequisite_reports_manual_apt_command_without_installing(self):
        for missing in ("venv", "asound", "python"):
            with self.subTest(missing=missing):
                self.env["INSTALLER_TEST_MISSING"] = missing
                result = self.run_script("--check")
                self.assertEqual(result.returncode, 1)
                self.assertIn("sudo apt install python3 python3-venv libasound2t64", result.stderr)
                self.assertFalse(self.data.exists())
                self.assertFalse(self.launcher.exists())

    def test_terminal_install_does_not_require_tkinter_or_create_desktop(self):
        self.env["INSTALLER_TEST_MISSING"] = "tkinter"
        result = self.run_script("--allow-unsupported")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.launcher.is_file())
        self.assertFalse((self.data / "applications").exists())
        self.assertEqual([args for kind, args in self.commands() if kind == "runtime"], [["--help"]])

    def test_install_preserves_checkout_and_builds_from_private_source_copy(self):
        before = {str(path.relative_to(self.source)): path.read_bytes()
                  for path in self.source.rglob("*") if path.is_file()}
        result = self.run_script("--allow-unsupported")
        self.assertEqual(result.returncode, 0, result.stderr)
        after = {str(path.relative_to(self.source)): path.read_bytes()
                 for path in self.source.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(len(self.releases), 1)
        self.assertFalse((self.releases[0] / "build-source").exists())
        pip_args = [args for kind, args in self.commands() if kind == "pip"]
        self.assertEqual(len(pip_args), 1)
        self.assertNotEqual(pip_args[0][-1], str(self.source))
        self.assertTrue(pip_args[0][-1].startswith(str(self.releases[0])))
        metadata = json.loads((self.releases[0] / "installation.json").read_text())
        self.assertEqual(metadata["launcher"], str(self.launcher))

    def test_launcher_preserves_arguments_and_supports_shell_metacharacters(self):
        self.home = self.root / "home '$ literal % `uname` \\ quoted"
        self.home.mkdir()
        self.data = self.home / "share"
        result = self.run_script("--allow-unsupported")
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = ["--help", "with spaces", "$unchanged", "`uname`", "double\"quote"]
        ran = subprocess.run([str(self.launcher), *arguments], env=self.env, capture_output=True, timeout=10)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(self.commands()[-1], ["runtime", arguments])
        self.assertFalse((self.home / "uname").exists())

    def test_existing_unmanaged_launcher_is_never_overwritten(self):
        self.launcher.parent.mkdir(parents=True)
        self.launcher.write_text("existing program\n")
        result = self.run_script("--allow-unsupported")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.launcher.read_text(), "existing program\n")
        self.assertEqual(self.releases, [])
        self.assertFalse(any(kind == "pip" for kind, _ in self.commands()))

    def test_symlink_launcher_is_never_replaced(self):
        self.launcher.parent.mkdir(parents=True)
        target = self.root / "unrelated-program"
        target.write_text("# EVOLINUX managed user launcher v1\n")
        self.launcher.symlink_to(target)
        result = self.run_script("--allow-unsupported")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.launcher.is_symlink())
        self.assertEqual(target.read_text(), "# EVOLINUX managed user launcher v1\n")

    def test_failed_pip_preserves_previous_working_installation(self):
        initial = self.run_script("--allow-unsupported")
        self.assertEqual(initial.returncode, 0, initial.stderr)
        prior_launcher, prior_releases = self.launcher.read_bytes(), self.releases
        self.env["INSTALLER_TEST_PIP_FAIL"] = "1"
        failure = self.run_script("--allow-unsupported")
        self.assertNotEqual(failure.returncode, 0)
        self.assertEqual(self.launcher.read_bytes(), prior_launcher)
        self.assertEqual(self.releases, prior_releases)

    def test_failed_runtime_help_does_not_activate_new_installation(self):
        self.env["INSTALLER_TEST_HELP_FAIL"] = "1"
        failure = self.run_script("--allow-unsupported")
        self.assertNotEqual(failure.returncode, 0)
        self.assertFalse(self.launcher.exists())
        self.assertFalse((self.data / "applications").exists())
        self.assertEqual(self.releases, [])

    def test_successful_update_keeps_old_release_and_switches_launcher(self):
        first = self.run_script("--allow-unsupported")
        self.assertEqual(first.returncode, 0, first.stderr)
        old_release = self.releases[0]
        old_launcher = self.launcher.read_bytes()
        second = self.run_script("--allow-unsupported")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(len(self.releases), 2)
        self.assertTrue((old_release / "venv" / "bin" / "evolinux").is_file())
        self.assertNotEqual(self.launcher.read_bytes(), old_launcher)

    def test_error_after_launcher_replacement_preserves_active_executable(self):
        initial = self.run_script("--allow-unsupported")
        self.assertEqual(initial.returncode, 0, initial.stderr)
        old_release = self.releases[0]
        old_launcher = self.launcher.read_bytes()
        self.env["INSTALLER_TEST_ACTIVATION_FAIL"] = "1"
        # A noncanonical absolute spelling must still identify the same
        # release when the shell performs cleanup after the helper error.
        failure = self.run_script("--allow-unsupported", "--prefix", str(self.home) + "/./")
        self.assertEqual(failure.returncode, 42, failure.stderr)
        self.assertNotEqual(self.launcher.read_bytes(), old_launcher)
        self.assertEqual(len(self.releases), 2)
        self.assertTrue((old_release / "venv" / "bin" / "evolinux").is_file())
        active_release = next(path for path in self.releases if path != old_release)
        metadata = json.loads((active_release / "installation.json").read_text())
        self.assertTrue(Path(metadata["executable"]).is_file())
        ran = subprocess.run([str(self.launcher), "--help"], env=self.env,
                             capture_output=True, timeout=10)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(self.commands()[-1], ["runtime", ["--help"]])

    def test_relative_prefix_fails_without_creating_files(self):
        result = self.run_script("--allow-unsupported", "--prefix", "relative-path")
        self.assertEqual(result.returncode, 1)
        self.assertIn("absolutos", result.stderr)
        self.assertFalse(self.launcher.exists())
        self.assertFalse(self.data.exists())

    def test_invalid_option_fails_before_prerequisite_checks(self):
        result = self.run_script("--unknown")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.commands(), [])


if __name__ == "__main__":
    unittest.main()

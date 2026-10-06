"""Bounded crash-bootstrap checks; no Torch, Isaac Sim or native task calls."""
import ctypes
import errno
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

from benchmarks.simBenchmarks.Behavior.environment import crash_handler as bootstrap


class FakeLibc:
    """Only manipulates ctypes structure fields, never native pointers."""
    def __init__(self, *, minimum=2048, previous_size=8192):
        self.pointer, self.size, self.flags = 4096, previous_size, 0
        self.query_count = 0
        self.query_error_at = None
        self.install_error = None
        self.readback_mismatch = False
        self.sigaltstack = Mock(side_effect=self.stack_call)
        self.getauxval = Mock(return_value=minimum)
        self.malloc = Mock(return_value=65536)
        self.free = Mock()

    def stack_call(self, new, old):
        if new is None:
            self.query_count += 1
            if self.query_count == self.query_error_at:
                ctypes.set_errno(errno.EINVAL)
                return -1
            old._obj.ss_sp = self.pointer
            old._obj.ss_size = self.size + int(self.readback_mismatch and self.query_count > 1)
            old._obj.ss_flags = self.flags
            return 0
        if self.install_error:
            ctypes.set_errno(self.install_error)
            return -1
        self.pointer, self.size, self.flags = new._obj.ss_sp, new._obj.ss_size, new._obj.ss_flags
        return 0


class MockBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.libc = FakeLibc()
        self.cdll = self.stack.enter_context(patch.object(bootstrap.ctypes, "CDLL", return_value=self.libc))
        self.stack.enter_context(patch.object(bootstrap.sys, "platform", "linux"))
        self.stack.enter_context(patch.object(bootstrap.platform, "machine", return_value="x86_64"))
        self.stack.enter_context(patch.dict(bootstrap.sys._xoptions, {"faulthandler": True}))
        self.stack.enter_context(patch.object(bootstrap.faulthandler, "is_enabled", return_value=True))
        self.enable = self.stack.enter_context(patch.object(bootstrap.faulthandler, "enable"))
        self.stack.enter_context(patch.object(bootstrap, "_allocation", None))
        self.stack.enter_context(patch.object(bootstrap, "_receipt", None))

    def test_successful_registration_uses_process_lifetime_allocation(self):
        receipt = bootstrap.prepare_crash_handler()
        self.assertEqual(receipt["stack_bytes"], 65536)
        self.assertEqual(receipt["previous_stack_bytes"], 8192)
        self.assertEqual(receipt["thread_scope"], "worker-main-thread")
        self.assertEqual(receipt["allocation_lifetime"], "process")
        self.libc.malloc.assert_called_once_with(65536)
        self.libc.getauxval.assert_called_once_with(51)
        self.libc.free.assert_not_called()
        self.enable.assert_called_once_with()
        self.cdll.assert_called_once_with(None, use_errno=True)
        self.assertIs(self.libc.malloc.restype, ctypes.c_void_p)
        self.assertEqual(self.libc.malloc.argtypes, [ctypes.c_size_t])

    def test_dynamic_minimum_and_existing_stack_are_not_undersized(self):
        for minimum, previous, expected in ((20000, 8192, 80000), (1024, 131072, 131072)):
            with self.subTest(minimum=minimum, previous=previous):
                bootstrap._allocation = bootstrap._receipt = None
                self.libc = FakeLibc(minimum=minimum, previous_size=previous)
                self.cdll.return_value = self.libc
                self.assertEqual(bootstrap.prepare_crash_handler()["stack_bytes"], expected)
                self.libc.malloc.assert_called_once_with(expected)

    def test_unsupported_platform_or_machine_fails_before_libc(self):
        for target, value in ((bootstrap.sys, "darwin"), (bootstrap.platform, "aarch64")):
            with self.subTest(value=value):
                context = (patch.object(target, "platform", value) if target is bootstrap.sys
                           else patch.object(target, "machine", return_value=value))
                with context, self.assertRaises(RuntimeError):
                    bootstrap.prepare_crash_handler()
        self.cdll.assert_not_called()

    def test_wrong_pointer_or_structure_abi_fails_before_libc(self):
        actual = ctypes.sizeof
        for changed, invalid in ((ctypes.c_void_p, 4), (bootstrap._Stack, 20)):
            with self.subTest(changed=changed):
                with patch.object(bootstrap.ctypes, "sizeof", side_effect=lambda value: invalid if value is changed else actual(value)):
                    with self.assertRaises(RuntimeError):
                        bootstrap.prepare_crash_handler()
        self.cdll.assert_not_called()

    def test_non_main_thread_fails_before_libc(self):
        with patch.object(bootstrap.threading, "current_thread", return_value=object()):
            with self.assertRaises(RuntimeError):
                bootstrap.prepare_crash_handler()
        self.cdll.assert_not_called()

    def test_requires_real_early_enabled_handler(self):
        with patch.dict(bootstrap.sys._xoptions, {}, clear=True), self.assertRaises(RuntimeError):
            bootstrap.prepare_crash_handler()
        with patch.object(bootstrap.faulthandler, "is_enabled", return_value=False), self.assertRaises(RuntimeError):
            bootstrap.prepare_crash_handler()
        self.cdll.assert_not_called()

    def test_initial_query_syscall_error_does_not_allocate(self):
        self.libc.query_error_at = 1
        with self.assertRaises(OSError) as error:
            bootstrap.prepare_crash_handler()
        self.assertEqual(error.exception.errno, errno.EINVAL)
        self.libc.malloc.assert_not_called()
        self.libc.free.assert_not_called()

    def test_invalid_existing_stack_flags_or_missing_buffer_fail_closed(self):
        for pointer, size, flags in ((4096, 8192, 1), (4096, 8192, 2), (4096, 8192, 1 << 31),
                                      (0, 8192, 0), (4096, 0, 0)):
            with self.subTest(pointer=pointer, size=size, flags=flags):
                self.libc.pointer, self.libc.size, self.libc.flags = pointer, size, flags
                with self.assertRaises(RuntimeError):
                    bootstrap.prepare_crash_handler()
        self.libc.malloc.assert_not_called()

    def test_oversized_dynamic_requirement_fails_before_allocation(self):
        self.libc.getauxval.return_value = 1024 * 1024
        with self.assertRaises(RuntimeError):
            bootstrap.prepare_crash_handler()
        self.libc.malloc.assert_not_called()

    def test_null_malloc_fails_without_registering_or_free(self):
        self.libc.malloc.return_value = None
        with self.assertRaises(MemoryError):
            bootstrap.prepare_crash_handler()
        self.assertEqual(self.libc.sigaltstack.call_count, 1)
        self.libc.free.assert_not_called()

    def test_failed_install_frees_only_never_registered_allocation(self):
        self.libc.install_error = errno.ENOMEM
        with self.assertRaises(OSError) as error:
            bootstrap.prepare_crash_handler()
        self.assertEqual(error.exception.errno, errno.ENOMEM)
        self.libc.free.assert_called_once_with(65536)
        self.assertIsNone(bootstrap._allocation)
        self.assertIsNone(bootstrap._receipt)
        self.enable.assert_not_called()

    def test_failed_readback_never_frees_registered_memory(self):
        self.libc.query_error_at = 2
        with self.assertRaises(OSError):
            bootstrap.prepare_crash_handler()
        self.libc.free.assert_not_called()
        self.assertEqual(bootstrap._allocation, 65536)
        self.enable.assert_not_called()

    def test_readback_mismatch_never_frees_registered_memory(self):
        self.libc.readback_mismatch = True
        with self.assertRaises(RuntimeError):
            bootstrap.prepare_crash_handler()
        self.libc.free.assert_not_called()
        self.assertEqual(bootstrap._allocation, 65536)

    def test_real_handler_enable_failure_is_not_swallowed_or_freed(self):
        self.enable.side_effect = RuntimeError("real handler failure")
        with self.assertRaisesRegex(RuntimeError, "real handler failure"):
            bootstrap.prepare_crash_handler()
        self.libc.free.assert_not_called()
        self.assertEqual(bootstrap._allocation, 65536)
        self.assertIsNone(bootstrap._receipt)

    def test_repeated_call_is_idempotent_and_returns_receipt_copy(self):
        first = bootstrap.prepare_crash_handler()
        second = bootstrap.prepare_crash_handler()
        self.assertEqual(first, second)
        first["stack_bytes"] = 0
        self.assertEqual(bootstrap.prepare_crash_handler()["stack_bytes"], 65536)
        self.libc.malloc.assert_called_once()
        self.libc.free.assert_not_called()
        self.enable.assert_called_once()

    def test_dependency_replacing_pointer_or_size_is_detected_not_repaired(self):
        bootstrap.prepare_crash_handler()
        for pointer, size in ((77777, 65536), (65536, 131072)):
            with self.subTest(pointer=pointer, size=size):
                self.libc.pointer, self.libc.size = pointer, size
                with self.assertRaisesRegex(RuntimeError, "replaced"):
                    bootstrap.prepare_crash_handler()
        self.libc.malloc.assert_called_once()
        self.libc.free.assert_not_called()
        self.enable.assert_called_once()


CHILD = r'''
import faulthandler, json, os, resource, sys
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
original = faulthandler.enable
from benchmarks.simBenchmarks.Behavior.environment.crash_handler import prepare_crash_handler
first = prepare_crash_handler()
assert prepare_crash_handler() == first
assert faulthandler.enable is original
assert faulthandler.is_enabled()
faulthandler.enable()
assert prepare_crash_handler() == first
assert not any(name == "torch" or name.startswith(("torch.", "omnigibson", "isaacsim")) for name in sys.modules)
print(json.dumps(first), flush=True)
def abort_with_real_handler():
    os.abort()
if sys.argv[1] == "abort":
    abort_with_real_handler()
'''


@unittest.skipUnless(sys.platform == "linux" and platform.machine() == "x86_64",
                     "actual signal-stack process check requires Linux x86-64")
class LinuxProcessTests(unittest.TestCase):
    def child(self, mode):
        repo = Path(__file__).resolve().parents[4]
        env = {**os.environ, "PYTHONPATH": str(repo), "PYTHONNOUSERSITE": "1"}
        with tempfile.TemporaryDirectory() as directory:
            return subprocess.run([sys.executable, "-X", "faulthandler", "-B", "-c", CHILD, mode],
                                  cwd=directory, env=env, capture_output=True, text=True, timeout=30)

    def test_early_handler_prepare_repeat_and_normal_exit(self):
        result = self.child("normal")
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertGreaterEqual(receipt["stack_bytes"], 65536)
        self.assertEqual(receipt["thread_scope"], "worker-main-thread")

    def test_genuine_abort_has_expected_signal_and_python_traceback(self):
        result = self.child("abort")
        self.assertEqual(result.returncode, -signal.SIGABRT, result.stderr)
        self.assertIn("Fatal Python error: Aborted", result.stderr)
        self.assertIn("abort_with_real_handler", result.stderr)
        self.assertGreaterEqual(json.loads(result.stdout)["stack_bytes"], 65536)


if __name__ == "__main__":
    unittest.main()

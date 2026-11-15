"""Worker-local Linux x86-64 signal stack, before importing the native SDK.

Keep CPython's actual handlers. Its early alternate stack can be too small for
AMX signal frames even when installing it before AMX avoids a late ENOMEM.
The replacement allocation intentionally lasts until process exit: Python's
finalizer must never leave a registered stack pointing to a collected buffer.
No simulator, task, action or scoring behavior is changed here.
"""
import ctypes
import faulthandler
import os
import platform
import sys
import threading

_allocation = None
_receipt = None


class _Stack(ctypes.Structure):
    # Linux x86-64 stack_t; do not assume this ABI on other platforms.
    _fields_ = [("ss_sp", ctypes.c_void_p), ("ss_flags", ctypes.c_int),
                ("ss_size", ctypes.c_size_t)]


def prepare_crash_handler():
    """Enlarge only this worker main thread's alternate stack, fail closed."""
    global _allocation, _receipt
    if (sys.platform != "linux" or platform.machine() != "x86_64"
            or ctypes.sizeof(ctypes.c_void_p) != 8 or ctypes.sizeof(_Stack) != 24
            or (_Stack.ss_sp.offset, _Stack.ss_flags.offset, _Stack.ss_size.offset) != (0, 8, 16)):
        raise RuntimeError("BEHAVIOR crash-handler bootstrap requires Linux x86-64")
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("crash-handler bootstrap must run in the worker main thread")
    if "faulthandler" not in sys._xoptions or not faulthandler.is_enabled():
        raise RuntimeError("native worker requires Python -X faulthandler at startup")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.sigaltstack.argtypes = [ctypes.POINTER(_Stack), ctypes.POINTER(_Stack)]
    libc.sigaltstack.restype = ctypes.c_int
    libc.getauxval.argtypes = [ctypes.c_ulong]
    libc.getauxval.restype = ctypes.c_ulong
    libc.malloc.argtypes = [ctypes.c_size_t]
    libc.malloc.restype = ctypes.c_void_p
    libc.free.argtypes = [ctypes.c_void_p]
    libc.free.restype = None

    def query():
        stack = _Stack()
        if libc.sigaltstack(None, ctypes.byref(stack)):
            raise OSError(ctypes.get_errno(), "cannot query native worker signal stack")
        if stack.ss_flags != 0 or not stack.ss_sp or not stack.ss_size:
            raise RuntimeError("worker signal stack is disabled, active or unexpected")
        return stack

    previous = query()
    if _receipt is not None:
        if previous.ss_sp != _allocation or previous.ss_size != _receipt["stack_bytes"]:
            raise RuntimeError("native dependency replaced the worker signal stack")
        return dict(_receipt)
    # AT_MINSIGSTKSZ=51 (Linux auxv). Some backported kernels under-report the
    # later AMX requirement; retain a conservative 64 KiB floor as well.
    minimum = int(libc.getauxval(51))
    size = max(64 * 1024, 4 * minimum, previous.ss_size)
    if size > 1024 * 1024:
        raise RuntimeError("unexpected signal-stack requirement exceeds 1 MiB")
    allocation = libc.malloc(size)
    if not allocation:
        raise MemoryError("cannot allocate native worker signal stack")
    replacement = _Stack(allocation, 0, size)
    if libc.sigaltstack(ctypes.byref(replacement), None):
        error = ctypes.get_errno()
        libc.free(allocation)  # Never registered: safe to release only here.
        raise OSError(error, "cannot install native worker signal stack")
    _allocation = allocation  # Never free while registered, including shutdown.
    current = query()
    if current.ss_sp != allocation or current.ss_size != size:
        raise RuntimeError("native worker signal-stack installation differs")
    faulthandler.enable()  # Real, already installed CPython handler; no patch.
    _receipt = {"schema": "starvla-rsi.behavior.worker-crash-handler/v1", "handler_enabled": True,
                "pid": os.getpid(), "tid": threading.get_native_id(),
                "early_python_option": True, "thread_scope": "worker-main-thread",
                "previous_stack_bytes": previous.ss_size, "stack_bytes": size,
                "auxv_minimum_bytes": minimum, "allocation_lifetime": "process"}
    return dict(_receipt)

"""Keep the core at full speed on Windows 11.

Found 2026-11-14 while timing a split part started the way the Rhino client starts the core (a
child python with no console window): Windows power throttling (EcoQoS) slows a busy background
process to about a third of its speed a few seconds into the work. The same split part took
2.6 s, then 9.8 s, then 10.8 s in one process; a pure-Python loop in that process slowed by the
same factor, and a fresh process was fast again. Opting the process out of execution-speed
throttling held it at 2.5 to 2.7 s for every run. This is the documented per-process switch
(SetProcessInformation, ProcessPowerThrottling); it changes nothing else and does nothing on
other systems. Failure is ignored: the core then runs as before, only slower.
"""
from __future__ import annotations

import sys

PROCESS_POWER_THROTTLING = 4  # PROCESS_INFORMATION_CLASS.ProcessPowerThrottling
EXECUTION_SPEED = 0x1  # PROCESS_POWER_THROTTLING_EXECUTION_SPEED


def keep_full_speed() -> bool:
    """Opt this process out of execution-speed throttling. True when Windows accepted it."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class State(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.SetProcessInformation.restype = wintypes.BOOL
        state = State(1, EXECUTION_SPEED, 0)  # we control execution speed, and it is not throttled
        return bool(k32.SetProcessInformation(k32.GetCurrentProcess(), PROCESS_POWER_THROTTLING,
                                              ctypes.byref(state), ctypes.sizeof(state)))
    except (OSError, AttributeError, ValueError):
        return False


def exit_with_parent() -> bool:
    """In a pool worker: exit as soon as the process that started it ends. Found 2026-11-14: when the
    Rhino client kills the core, ProcessPoolExecutor workers on Windows stay alive, idle, forever (nine
    per killed core). A daemon thread waits on the parent's process handle and ends this worker."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        import os
        import threading
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.WaitForSingleObject.restype = wintypes.DWORD
        handle = k32.OpenProcess(0x00100000, False, os.getppid())  # SYNCHRONIZE
        if not handle:
            return False

        def wait() -> None:
            k32.WaitForSingleObject(handle, 0xFFFFFFFF)  # INFINITE
            os._exit(0)

        threading.Thread(target=wait, name="gnj-exit-with-parent", daemon=True).start()
        return True
    except (OSError, AttributeError, ValueError):
        return False


def worker_init() -> None:
    """ProcessPoolExecutor initializer for the piece fits."""
    keep_full_speed()
    exit_with_parent()

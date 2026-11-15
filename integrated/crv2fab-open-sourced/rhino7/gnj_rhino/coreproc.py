# -*- coding: utf-8 -*-
"""The nudge core as a child process, when nothing answers on its port."""
from gnj_rhino.common import *  # noqa: F401,F403
from gnj_rhino.doc import *  # noqa: F401,F403
from gnj_rhino.gesture import *  # noqa: F401,F403
from gnj_rhino.geometry import *  # noqa: F401,F403
from gnj_rhino.scenes import *  # noqa: F401,F403
from gnj_rhino.conduit import *  # noqa: F401,F403


# ---------------------------------------------------------------- the nudge core as a child process

def core_port_open(timeout=0.3):
    import socket
    try:
        sock = socket.create_connection(("127.0.0.1", 8742), timeout)
        sock.close()
        return True
    except Exception:
        return False


def start_core_child(wait_s=5.0):
    """Start the core when nothing listens on 8742. Returns the child process (ours to stop) or None."""
    if core_port_open():
        return None
    if CORE_DIR is None:
        Rhino.RhinoApp.WriteLine("GNJ: the nudge core was not found. Run install.ps1, or set GNJ_CORE_DIR "
                                 "to the folder that holds gnj_nudge.")
        return None
    try:
        psi = System.Diagnostics.ProcessStartInfo(CORE_PYTHON, "-m gnj_nudge.server")
        psi.WorkingDirectory = CORE_DIR
        psi.UseShellExecute = False
        psi.CreateNoWindow = True
        proc = System.Diagnostics.Process.Start(psi)
    except Exception as ex:
        Rhino.RhinoApp.WriteLine("GNJ: could not start the nudge core: %s" % ex)
        return None
    end = time.time() + wait_s
    while time.time() < end:
        if core_port_open():
            Rhino.RhinoApp.WriteLine("GNJ: started the nudge core (pid %d); it stops when the panel closes." % proc.Id)
            return proc
        if proc.HasExited:
            break
        time.sleep(0.2)
    Rhino.RhinoApp.WriteLine("GNJ: the nudge core did not answer within %g s." % wait_s)
    return proc


def stop_core_child(proc):
    if proc is None:
        return
    try:
        if not proc.HasExited:
            proc.Kill()
            proc.WaitForExit(2000)
    except Exception as ex:
        Rhino.RhinoApp.WriteLine("GNJ: could not stop the nudge core child: %s" % ex)

__all__ = [_n for _n in dir() if not _n.startswith("__")]  # every name, underscores too

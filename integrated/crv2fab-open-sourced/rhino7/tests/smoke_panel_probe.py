# -*- coding: utf-8 -*-
"""Feasibility probe: can a Rhino 7 IronPython script put a tab in Rhino's own docked panel area?

Run ONLY in a fresh test instance with its own settings scheme, so no panel layout is saved
into the user's default scheme:
  "C:\\Program Files\\Rhino 7\\System\\Rhino.exe" /nosplash /scheme=GNJSmoke
      /runscript="_-RunPythonScript C:\\...\\tests\\smoke_panel_probe.py _-Exit _No"

A1  Rhino.UI.Panels.RegisterPanel with a type defined in Python.
A2  The same with a tiny Guid-attributed panel class compiled in memory from C# at run time
    (.NET's own CodeDom compiler; no file installed, nothing registered with the plug-in manager),
    owned by the IronPython plug-in's PlugIn object. Open it, put a Python-built Eto control in it,
    capture the Rhino window (PrintWindow: Rhino's own pixels only), close it again.
"""
import os
import sys
import time
import traceback

OUT = os.environ.get("GNJ_SMOKE_DIR", r"C:\Users\danie\scratch\2026-11-14")
LOG = os.path.join(OUT, "gnj-rhino7-panel-probe.log")
PANEL_GUID = "6a1d2c4e-9b1f-4f0e-8d2a-3c5b7e9f1a20"
log = open(LOG, "w")


def say(*parts):
    log.write(" ".join("%s" % (p,) for p in parts) + "\n")
    log.flush()


try:
    import clr
    import System
    import Rhino
    import Eto.Forms as forms
    import Eto.Drawing as drawing

    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            Rhino.RhinoApp.Wait()
            time.sleep(0.05)

    py_plugin = None
    for kv in Rhino.PlugIns.PlugIn.GetInstalledPlugIns():   # a .NET Dictionary: KeyValuePairs
        pid, name = kv.Key, kv.Value
        if "python" in (name or "").lower():
            py_plugin = Rhino.PlugIns.PlugIn.Find(pid)
            say("python plug-in:", name, pid, "| object:", py_plugin)
            if py_plugin is not None:
                break
    icon = System.Drawing.SystemIcons.Application

    # ---- A1: a panel type written in Python
    class PyPanel(forms.Panel):
        pass
    try:
        t = clr.GetClrType(PyPanel)
        say("A1 type:", t.FullName, "| GUID:", t.GUID)
        Rhino.UI.Panels.RegisterPanel(py_plugin, t, "CRV2FAB-A1", icon)
        say("A1 RegisterPanel returned without error")
        Rhino.UI.Panels.OpenPanel(t.GUID)
        pump(1.0)
        say("A1 open/visible:", Rhino.UI.Panels.IsPanelVisible(t.GUID))
        Rhino.UI.Panels.ClosePanel(t.GUID)
    except Exception as ex:
        say("A1 FAILED:", ex.__class__.__name__, ex)

    # ---- A2: a Guid-attributed panel class compiled in memory
    src = """
using System;
using System.Runtime.InteropServices;
namespace Crv2fab {
  [Guid("%s")]
  public class SystemPanel : Eto.Forms.Panel {
    public static SystemPanel Instance;
    public SystemPanel() { Instance = this; }
    public SystemPanel(uint documentSerialNumber) : this() { }
  }
}
""" % PANEL_GUID
    from Microsoft.CSharp import CSharpCodeProvider
    from System.CodeDom.Compiler import CompilerParameters
    cp = CompilerParameters()
    cp.GenerateInMemory = True
    cp.GenerateExecutable = False
    runtime = System.IO.Path.GetDirectoryName(clr.GetClrType(System.Object).Assembly.Location)
    for ref in ("System.dll", clr.GetClrType(forms.Panel).Assembly.Location,
                System.IO.Path.Combine(runtime, "netstandard.dll")):
        cp.ReferencedAssemblies.Add(ref)
    t0 = time.time()
    res = CSharpCodeProvider().CompileAssemblyFromSource(cp, System.Array[str]([src]))
    say("A2 compile %.2f s, errors:" % (time.time() - t0), [e.ToString() for e in res.Errors] or "none")
    if not res.Errors.HasErrors:
        ptype = res.CompiledAssembly.GetType("Crv2fab.SystemPanel")
        guid = System.Guid(PANEL_GUID)
        say("A2 type:", ptype.FullName, "| GUID matches:", ptype.GUID == guid)
        try:
            Rhino.UI.Panels.RegisterPanel(py_plugin, ptype, "CRV2FAB", icon)
            say("A2 registered")
            names = sorted(set(m.Name for m in clr.GetClrType(Rhino.UI.Panels).GetMethods()
                               if "Sibling" in m.Name or "Dock" in m.Name or "Float" in m.Name or m.Name.startswith("Open")))
            say("A2 Panels methods:", names)
            layers = Rhino.UI.PanelIds.Layers
            Rhino.UI.Panels.OpenPanel(layers)            # a panel that lives in the right-hand container
            pump(0.8)
            try:
                Rhino.UI.Panels.OpenPanelAsSibling(guid, layers)
                say("A2 opened as a sibling tab of Layers")
            except Exception as ex:
                say("A2 OpenPanelAsSibling failed:", ex, "| falling back to OpenPanel")
                Rhino.UI.Panels.OpenPanel(guid)
            pump(1.5)
            try:
                say("A2 floating:", Rhino.UI.Panels.IsPanelFloating(guid) if hasattr(Rhino.UI.Panels, "IsPanelFloating") else "n/a",
                    "| dock bars:", [str(g) for g in Rhino.UI.Panels.PanelDockBars(guid)] if hasattr(Rhino.UI.Panels, "PanelDockBars") else "n/a",
                    "| layers dock bars:", [str(g) for g in Rhino.UI.Panels.PanelDockBars(layers)] if hasattr(Rhino.UI.Panels, "PanelDockBars") else "n/a")
            except Exception as ex:
                say("A2 dock query failed:", ex)
            inst = ptype.GetField("Instance").GetValue(None)
            say("A2 visible:", Rhino.UI.Panels.IsPanelVisible(guid), "| instance:", inst is not None)
            if inst is not None:
                body = forms.TableLayout()
                body.Padding = drawing.Padding(12)
                body.Spacing = drawing.Size(0, 8)
                for text in ("CRV2FAB", "Inputs", "Settings", "Numbers", "Output", "Display", "Record",
                             "This content is a Python Eto control handed to the docked panel."):
                    lbl = forms.Label()
                    lbl.Text = text
                    body.Rows.Add(forms.TableRow(forms.TableCell(lbl, True)))
                body.Rows.Add(forms.TableRow())
                inst.Content = body
                pump(1.5)
                wpf = inst.ControlObject
                say("A2 content set | panel size %s x %s" % (wpf.ActualWidth, wpf.ActualHeight))
                # Capture Rhino's own window, even if something covers it on screen.
                import ctypes
                hwnd = Rhino.RhinoApp.MainWindowHandle()
                rect = ctypes.create_string_buffer(16)
                ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(hwnd.ToInt64()), rect)
                import struct
                l, t_, r, b = struct.unpack("4i", rect.raw)
                bmp = System.Drawing.Bitmap(r - l, b - t_)
                g = System.Drawing.Graphics.FromImage(bmp)
                hdc = g.GetHdc()
                ok = ctypes.windll.user32.PrintWindow(ctypes.c_void_p(hwnd.ToInt64()), ctypes.c_void_p(hdc.ToInt64()), 2)
                g.ReleaseHdc(hdc)
                g.Dispose()
                path = os.path.join(OUT, "gnj-rhino7-panel-probe-window.png")
                bmp.Save(path)
                say("A2 window capture", ok, path, "| %dx%d" % (r - l, b - t_))
            Rhino.UI.Panels.ClosePanel(guid)
            pump(0.5)
            say("A2 closed; visible now:", Rhino.UI.Panels.IsPanelVisible(guid))
        except Exception as ex:
            say("A2 FAILED:", ex.__class__.__name__, ex)
            say(traceback.format_exc())
    say("PROBE DONE")
except Exception:
    say("PROBE FAILED")
    say(traceback.format_exc())
finally:
    try:
        import scriptcontext as sc
        sc.doc.Modified = False
    except Exception:
        pass
    log.close()

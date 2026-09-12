' Asset Library - silent launcher.  Double-click this.
'
' No console, ever - not hidden, not flashed, NOT THERE. The previous version
' ran python.exe through "cmd /c ... > launch.log 2>&1" with the window style
' set to hidden, which works but still creates a console-subsystem process:
' anything that stole focus at the wrong moment, or any child that made its own
' console, put a black window on screen.
'
' pythonw.exe is a GUI-subsystem binary. It cannot own a console, so there is
' nothing to hide and nothing to flash, and cmd.exe is gone from the chain.
'
' The cost of pythonw is that it has no stdout at all - a traceback would go
' nowhere. ui/app.py:_install_logging() buys that back: when sys.stdout is None
' it redirects both streams to launch.log and installs an excepthook, so a
' crash before the window exists is still written down.
'
' To watch output live while something is wrong, run the app from a console
' yourself:  runtime\python.exe -m ui.app   (python.exe, not pythonw).
'
' Paths are derived from this script's own location, so the whole project can
' be carried to any drive letter and this still works.

Option Explicit

Dim shell, fso, quote, base, exe, log, code
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
quote = Chr(34)

base = fso.GetParentFolderName(WScript.ScriptFullName)
exe = fso.BuildPath(base, "runtime\pythonw.exe")
log = fso.BuildPath(base, "launch.log")

' Fall back to python.exe rather than refusing to start: a runtime assembled by
' hand may not have pythonw, and a console window is a far smaller problem than
' an app that will not open.
If Not fso.FileExists(exe) Then
    exe = fso.BuildPath(base, "runtime\python.exe")
End If

If Not fso.FileExists(exe) Then
    MsgBox "runtime\pythonw.exe is missing." & vbCrLf & vbCrLf & _
           "The bundled Python has to travel with the project - copy the " & _
           "whole folder, runtime\ included.", _
           vbCritical, "Asset Library"
    WScript.Quit 1
End If

shell.CurrentDirectory = base

' Started directly. No cmd, no shell, no redirection - the app writes its own
' log now, which is why none is needed here.
code = shell.Run(quote & exe & quote & " -m ui.app", 1, True)

If code <> 0 Then
    If MsgBox("Asset Library exited with code " & code & "." & vbCrLf & vbCrLf & _
              "Open the log?", vbExclamation + vbYesNo, "Asset Library") = vbYes Then
        shell.Run "notepad.exe " & quote & log & quote, 1, False
    End If
End If

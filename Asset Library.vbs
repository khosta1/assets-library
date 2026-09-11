' Asset Library - silent launcher.  Double-click this.
'
' A .bat always flashes a console window, even when it starts pythonw.exe, so
' the launcher has to be something Windows does not give a console to at all.
'
' python.exe is used rather than pythonw.exe on purpose: pythonw discards
' stderr entirely, so a crash would leave nothing to look at. Here the console
' is simply never shown (Run window style 0) and its output is redirected to
' launch.log - silent when all is well, diagnosable when it is not.
'
' Paths are derived from this script's own location, so the whole project can
' be carried to any drive letter and this still works.

Option Explicit

Dim shell, fso, quote, base, exe, log, command, code
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
quote = Chr(34)

base = fso.GetParentFolderName(WScript.ScriptFullName)
exe = fso.BuildPath(base, "runtime\python.exe")
log = fso.BuildPath(base, "launch.log")

If Not fso.FileExists(exe) Then
    MsgBox "runtime\python.exe is missing." & vbCrLf & vbCrLf & _
           "The bundled Python has to travel with the project - copy the " & _
           "whole folder, runtime\ included.", _
           vbCritical, "Asset Library"
    WScript.Quit 1
End If

shell.CurrentDirectory = base

' cmd /c ""<exe>" -m ui.app > "<log>" 2>&1"
command = "cmd /c " & quote & quote & exe & quote & " -m ui.app > " & _
          quote & log & quote & " 2>&1" & quote

code = shell.Run(command, 0, True)

If code <> 0 Then
    If MsgBox("Asset Library exited with code " & code & "." & vbCrLf & vbCrLf & _
              "Open the log?", vbExclamation + vbYesNo, "Asset Library") = vbYes Then
        shell.Run "notepad.exe " & quote & log & quote, 1, False
    End If
End If

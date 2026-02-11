On Error Resume Next

Set FSO = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

ScriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)

VenvPython = FSO.BuildPath(ScriptDir, ".venv\Scripts\python.exe")
RunScript = FSO.BuildPath(ScriptDir, "run.py")

WshShell.CurrentDirectory = ScriptDir

If Not FSO.FileExists(RunScript) Then
    MsgBox "run.py not found: " & RunScript, vbCritical, "OmniConv"
    WScript.Quit 1
End If

If FSO.FileExists(VenvPython) Then
    WshShell.Run Chr(34) & VenvPython & Chr(34) & " " & Chr(34) & RunScript & Chr(34), 0, False
Else
    WshShell.Run "python " & Chr(34) & RunScript & Chr(34), 0, False
End If

If Err.Number <> 0 Then
    MsgBox "Failed to start OmniConv: " & Err.Description, vbCritical, "OmniConv"
    WScript.Quit 1
End If
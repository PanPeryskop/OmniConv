Set FSO = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

' Get the absolute path to the directory containing this script
ScriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)

' Construct absolute paths
VenvPython = FSO.BuildPath(ScriptDir, ".venv\Scripts\python.exe")
RunScript = FSO.BuildPath(ScriptDir, "run.py")

' Set working directory to script directory to ensure app finds its resources
WshShell.CurrentDirectory = ScriptDir

If FSO.FileExists(VenvPython) Then
    ' Run using virtual environment python
    ' Use Chr(34) for quotes to handle paths with spaces safely
    WshShell.Run Chr(34) & VenvPython & Chr(34) & " " & Chr(34) & RunScript & Chr(34), 0, False
Else
    ' Fallback to system python
    WshShell.Run "python " & Chr(34) & RunScript & Chr(34), 0, False
End If
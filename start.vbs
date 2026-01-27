Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

If CreateObject("Scripting.FileSystemObject").FileExists(".venv\Scripts\python.exe") Then
    WshShell.Run """.venv\Scripts\python.exe"" run.py", 0, False
Else
    WshShell.Run "python run.py", 0, False
End If
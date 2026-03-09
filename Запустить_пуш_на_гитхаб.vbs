Option Explicit
Dim fso, scriptDir, wsh
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set wsh = CreateObject("WScript.Shell")
wsh.CurrentDirectory = scriptDir
wsh.Run "cmd /k """ & scriptDir & "\ПУШ_НА_ГИТХАБ.bat""", 1, False

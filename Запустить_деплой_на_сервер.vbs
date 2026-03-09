Option Explicit
Dim fso, scriptDir, wsh
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set wsh = CreateObject("WScript.Shell")
wsh.CurrentDirectory = scriptDir
wsh.Run "cmd /k """ & scriptDir & "\ДЕПЛОЙ_НА_СЕРВЕР.bat""", 1, False

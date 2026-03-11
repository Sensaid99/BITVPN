Option Explicit
Dim fso, scriptDir, wsh, q
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
q = Chr(34)
Set wsh = CreateObject("WScript.Shell")
wsh.CurrentDirectory = scriptDir
wsh.Run "cmd /k " & q & "cd /d " & q & scriptDir & q & " && ДЕПЛОЙ_НА_СЕРВЕР.bat" & q, 1, False

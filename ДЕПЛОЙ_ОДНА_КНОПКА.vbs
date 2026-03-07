' Запуск деплоя одной кнопкой. Окно CMD откроется и останется открытым (можно прочитать вывод и ошибки).
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
bat = fso.BuildPath(dir, "deploy_server.bat")
' 1 = обычное окно, True = ждать. /k = не закрывать окно после выполнения — так видно результат и ошибки.
CreateObject("WScript.Shell").Run "cmd /k ""cd /d """ & dir & """ && """ & bat & """""", 1, True

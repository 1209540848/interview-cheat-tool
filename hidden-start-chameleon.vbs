' interview-cheat-tool - API 祖本启动器（静默，--chameleon 无控制台闪窗）
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
Set ws = CreateObject("Wscript.Shell")
py = "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe"
If Not fso.FileExists(py) Then py = "python"
ws.CurrentDirectory = base
ws.Run """" & py & """ """ & base & "\interview-cheat-api.py"" --chameleon", 0, False

' interview-cheat-tool - 测评版启动器（静默，无控制台闪窗）
' 自动找 Python：优先本机固定路径，找不到就用 PATH 里的 python
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
Set ws = CreateObject("Wscript.Shell")
py = "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe"
If Not fso.FileExists(py) Then py = "python"
ws.CurrentDirectory = base
ws.Run """" & py & """ """ & base & "\interview-cheat-quiz.py"" --chameleon", 0, False

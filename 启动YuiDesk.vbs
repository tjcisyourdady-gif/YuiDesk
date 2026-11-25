Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = baseDir & "\.venv\Scripts\pythonw.exe"
mainPy = baseDir & "\main.py"
sh.CurrentDirectory = baseDir
' pythonw.exe 本身无黑框；参数必须为 1 (SW_SHOWNORMAL)，若为 0 会导致首个 Qt 桌宠窗口被 Windows 隐藏
sh.Run """" & pyw & """ """ & mainPy & """", 1, False

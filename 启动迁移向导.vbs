' Start amigrate web server in background (no console window), then open browser
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "E:\auto-IC-move"
sh.Run """D:\Python312\pythonw.exe"" tools\webui.py", 0, False
WScript.Sleep 1800
sh.Run "http://127.0.0.1:8800"
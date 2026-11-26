' Launch amigrate desktop UI silently (no console window)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "E:\auto-IC-move"
sh.Run """D:\Python312\pythonw.exe"" tools\amigrate_app.py", 0, False
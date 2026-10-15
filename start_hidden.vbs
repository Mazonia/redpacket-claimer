' Binance Red Packet Auto-Claimer - Silent Background Launcher
' Runs run.bat completely hidden in background without any visible command prompt window.
Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
strCurDir = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strCurDir
WshShell.Run "cmd.exe /c run.bat", 0, False

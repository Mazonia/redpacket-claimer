' Binance Red Packet Auto-Claimer - Silent Background Launcher
' Runs run.bat completely hidden in background without popping up visible windows.
Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
strCurDir = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strCurDir

' 1. Check if claimer or its supervisor is already running to prevent duplicate competing processes
Set objWMI = GetObject("winmgmts:{impersonationLevel=impersonate}!\\.\root\cimv2")
Set colProcesses = objWMI.ExecQuery("Select ProcessId, Name, CommandLine from Win32_Process Where Name = 'redpacket-claimer.exe'")

bAlreadyRunning = False
For Each objProc In colProcesses
    strCmd = ""
    On Error Resume Next
    strCmd = objProc.CommandLine
    On Error GoTo 0
    If InStr(1, strCmd, strCurDir, 1) > 0 Or InStr(1, strCmd, "main.py", 1) > 0 Then
        bAlreadyRunning = True
        Exit For
    End If
Next

If Not bAlreadyRunning Then
    Set colCmd = objWMI.ExecQuery("Select ProcessId, Name, CommandLine from Win32_Process Where Name = 'cmd.exe'")
    For Each objProc In colCmd
        strCmd = ""
        On Error Resume Next
        strCmd = objProc.CommandLine
        On Error GoTo 0
        If InStr(1, strCmd, "run.bat", 1) > 0 And InStr(1, strCmd, strCurDir, 1) > 0 Then
            bAlreadyRunning = True
            Exit For
        End If
    Next
End If

bSilent = False
For i = 0 To WScript.Arguments.Count - 1
    If LCase(WScript.Arguments(i)) = "/silent" Or LCase(WScript.Arguments(i)) = "-silent" Or LCase(WScript.Arguments(i)) = "--silent" Then
        bSilent = True
    End If
Next

If bAlreadyRunning Then
    If Not bSilent Then
        WshShell.Popup "Binance Red Packet Claimer is already running in the background." & vbCrLf & vbCrLf & "Use stop.bat to stop it if needed.", 4, "Claimer Already Running", 64
    End If
    WScript.Quit 0
End If

' 2. Launch run.bat hidden with --headless flag so no browser or console window pops up
strArgs = "--headless"
If WScript.Arguments.Count > 0 Then
    For i = 0 To WScript.Arguments.Count - 1
        If LCase(WScript.Arguments(i)) <> "/silent" And LCase(WScript.Arguments(i)) <> "-silent" And LCase(WScript.Arguments(i)) <> "--silent" Then
            strArgs = strArgs & " " & WScript.Arguments(i)
        End If
    Next
End If

WshShell.Run "cmd.exe /c run.bat " & strArgs, 0, False

If Not bSilent Then
    WshShell.Popup "Binance Red Packet Auto-Claimer started in background (Headless Mode)." & vbCrLf & vbCrLf & "To stop: run stop.bat" & vbCrLf & "To monitor: view claimed_cache.json", 3, "Claimer Started", 64
End If

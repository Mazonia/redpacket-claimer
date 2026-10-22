' Binance Red Packet Auto-Claimer - Silent Background Launcher
' Runs run.bat completely hidden in background without popping up visible windows.
Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
strCurDir = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strCurDir

' 0. Parse command line arguments
bSilent = False
strArgs = "--headless"
If WScript.Arguments.Count > 0 Then
    For i = 0 To WScript.Arguments.Count - 1
        arg = WScript.Arguments(i)
        If LCase(arg) = "/silent" Or LCase(arg) = "-silent" Or LCase(arg) = "--silent" Then
            bSilent = True
        Else
            strArgs = strArgs & " " & arg
        End If
    Next
End If

' 1. Race-condition prevention: Atomic single-startup file lock
' When multiple autostart triggers (Task Scheduler, Startup Folder, Registry) fire simultaneously on logon,
' this lock ensures only the very first one proceeds and the others cleanly and immediately exit.
strLockFile = strCurDir & "\start.lock"
Dim objLockFile
On Error Resume Next
Set objLockFile = FSO.OpenTextFile(strLockFile, 2, True) ' 2 = ForWriting, True = CreateIfNotExist
If Err.Number <> 0 Then
    ' Another launcher instance is currently launching; exit cleanly
    WScript.Quit 0
End If
On Error GoTo 0

' 2. Check if claimer or its supervisor is already running to prevent duplicate competing processes
Set objWMI = GetObject("winmgmts:{impersonationLevel=impersonate}!\\.\root\cimv2")
bAlreadyRunning = False

' Check for dedicated named executable: redpacket-claimer.exe
Set colProcesses = objWMI.ExecQuery("Select ProcessId, Name, ExecutablePath, CommandLine from Win32_Process Where Name = 'redpacket-claimer.exe'")
For Each objProc In colProcesses
    strCmd = ""
    strExe = ""
    On Error Resume Next
    strCmd = objProc.CommandLine
    strExe = objProc.ExecutablePath
    On Error GoTo 0
    If InStr(1, strCmd, strCurDir, 1) > 0 Or InStr(1, strCmd, "main.py", 1) > 0 Or InStr(1, strExe, strCurDir, 1) > 0 Or (strCmd = "" And strExe = "") Then
        bAlreadyRunning = True
        Exit For
    End If
Next

' Check for cmd.exe supervisor running run.bat in this directory
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

' Check for python.exe / pythonw.exe running main.py in this directory
If Not bAlreadyRunning Then
    Set colPy = objWMI.ExecQuery("Select ProcessId, Name, CommandLine from Win32_Process Where Name = 'python.exe' Or Name = 'pythonw.exe'")
    For Each objProc In colPy
        strCmd = ""
        On Error Resume Next
        strCmd = objProc.CommandLine
        On Error GoTo 0
        If InStr(1, strCmd, "main.py", 1) > 0 And InStr(1, strCmd, strCurDir, 1) > 0 Then
            bAlreadyRunning = True
            Exit For
        End If
    Next
End If

If bAlreadyRunning Then
    On Error Resume Next
    objLockFile.Close
    FSO.DeleteFile strLockFile, True
    On Error GoTo 0
    If Not bSilent Then
        WshShell.Popup "Binance Red Packet Claimer is already running in the background." & vbCrLf & vbCrLf & "Use stop.bat to stop it if needed.", 4, "Claimer Already Running", 64
    End If
    WScript.Quit 0
End If

' 3. Launch run.bat completely hidden (0 = SW_HIDE, False = async)
' Using "cmd.exe /c call ..." prevents Windows CMD from stripping outer quotes when strCurDir contains spaces
WshShell.Run "cmd.exe /c call """ & strCurDir & "\run.bat"" " & strArgs, 0, False

' Give run.bat a brief moment to spawn before releasing startup lock
WScript.Sleep 1500

On Error Resume Next
objLockFile.Close
FSO.DeleteFile strLockFile, True
On Error GoTo 0

If Not bSilent Then
    WshShell.Popup "Binance Red Packet Auto-Claimer started in background (Headless Mode)." & vbCrLf & vbCrLf & "To stop: run stop.bat" & vbCrLf & "To monitor: view claimed_cache.json", 3, "Claimer Started", 64
End If

Option Explicit
Dim fso, sh, scriptDir, exitCode, logPath, logText
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = scriptDir

' 0 = hidden window, True = tunggu sampai bat selesai supaya kita bisa baca exit code
exitCode = sh.Run("cmd /c run.bat hidden > run.log 2>&1", 0, True)

If exitCode <> 0 Then
    logText = ""
    logPath = scriptDir & "\run.log"
    If fso.FileExists(logPath) Then
        logText = vbCrLf & vbCrLf & "--- run.log ---" & vbCrLf & fso.OpenTextFile(logPath, 1).ReadAll()
    End If
    MsgBox "Sortir Stiker Pack gagal start (exit code " & exitCode & ")." & logText, vbCritical, "Sortir Stiker Pack"
End If

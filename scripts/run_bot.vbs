' run_bot.vbs — Wealth_Engine Bot Launcher
' VBScript cria processo verdadeiramente destacado (Windows nativo)
' Nao precisa de nenhum shell, sobrevive a logoffs

Dim objShell, objFSO, strCommand, strWorkDir, strLogPath

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

' Diretorio do projeto (mesmo deste script)
strWorkDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
strWorkDir = objFSO.GetParentFolderName(strWorkDir)  ' Sobe de scripts/ para raiz

' Caminho do Python venv
strPython = "C:\Users\lucas\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"

' Comando
strCommand = strPython & " -u bot/executor.py"

' Log path
strLogPath = strWorkDir & "\logs\dry_run.log"

' Garante que o diretorio logs existe
If Not objFSO.FolderExists(objFSO.GetParentFolderName(strLogPath)) Then
    objFSO.CreateFolder(objFSO.GetParentFolderName(strLogPath))
End If

' Executa sem janela (0 = hide window)
' bWaitOnReturn = False = assincrono
objShell.CurrentDirectory = strWorkDir
objShell.Run "cmd.exe /c """ & strCommand & " > """ & strLogPath & """ 2>&1""", 0, False

WScript.Echo "Bot lancado. PID do cmd.exe: " & "verifique via tasklist"
WScript.Echo "Log: " & strLogPath
WScript.Echo "Working dir: " & strWorkDir

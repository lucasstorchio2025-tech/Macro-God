' instalar_dashboard_startup.vbs
' Cria atalho do Wealth Engine COMPLETO na pasta Startup do Windows
' Inicia: Dashboard + Watchdog + Executor + Intelligence
'
' ⚠️  NOVO: usa start_all.bat (sistema completo), nao apenas o dashboard.
'    Recomendado: use instalar_startup_completo.ps1 (PowerShell) para mais opcoes.

Set WshShell = CreateObject("WScript.Shell")
StartupPath = WshShell.SpecialFolders("Startup")

' Caminho do atalho
ShortcutPath = StartupPath & "\Wealth_Engine_System.lnk"

' Verifica se ja existe
Set fso = CreateObject("Scripting.FileSystemObject")
If fso.FileExists(ShortcutPath) Then
    MsgBox "✅ Atalho do Wealth Engine ja existe!" & vbCrLf & _
           "O sistema completo ja inicia automaticamente ao ligar o PC." & vbCrLF & vbCrLf & _
           "📍 Dashboard: http://localhost:8501", _
           64, "Wealth Engine - Sistema"
    WScript.Quit 0
End If

' Cria o atalho
Set Shortcut = WshShell.CreateShortcut(ShortcutPath)
Shortcut.TargetPath = WshShell.ExpandEnvironmentStrings("USERPROFILE") & "\Wealth_Engine\bot\start_all.bat"
Shortcut.WorkingDirectory = WshShell.ExpandEnvironmentStrings("USERPROFILE") & "\Wealth_Engine"
Shortcut.WindowStyle = 7  ' Minimizado
Shortcut.Description = "Wealth Engine — Sistema Completo (Dashboard + Bot + Intel) - inicia automaticamente"
Shortcut.Save

MsgBox "✅ Atalho criado com sucesso!" & vbCrLf & vbCrLf & _
       "O Wealth Engine COMPLETO agora" & vbCrLf & _
       "inicia AUTOMATICAMENTE ao ligar o PC!" & vbCrLf & vbCrLf & _
       "📍 Dashboard: http://localhost:8501" & vbCrLf & _
       "📍 Status:     bot\status.bat" & vbCrLf & vbCrLf & _
       "🚀 Inicia: Dashboard + Watchdog + Executor + Intelligence", _
       64, "Wealth Engine - Sistema Instalado"

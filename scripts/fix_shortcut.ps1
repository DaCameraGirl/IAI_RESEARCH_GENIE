$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("C:\Users\enter\OneDrive\Desktop\AIA_Research_Assistant.lnk")
$Shortcut.TargetPath = "C:\Users\enter\OneDrive\Desktop\RWS_RESEARCH_BOT\Launch RWS Research Bot.bat"
$Shortcut.WorkingDirectory = "C:\Users\enter\OneDrive\Desktop\RWS_RESEARCH_BOT"
$Shortcut.IconLocation = "C:\Users\enter\OneDrive\Desktop\RWS_RESEARCH_BOT\assets\genie-mascot.ico"
$Shortcut.Description = "AIA Research Assistant"
$Shortcut.Save()
Write-Host "Shortcut updated successfully!"

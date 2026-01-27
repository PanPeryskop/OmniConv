@echo off
set "SCRIPT_DIR=%~dp0"
if not "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR%\"

set "TARGET_VBS=%SCRIPT_DIR%start.vbs"
set "ICON_PATH=%SCRIPT_DIR%app\static\ico.ico"
set "SHORTCUT_NAME=OmniConv.lnk"
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

echo Configuring autostart for OmniConv...

powershell -Command "$WshShell = New-Object -comObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%STARTUP_FOLDER%\%SHORTCUT_NAME%'); $Shortcut.TargetPath = 'wscript'; $Shortcut.Arguments = '//nologo \"%TARGET_VBS%\"'; $Shortcut.WorkingDirectory = '%SCRIPT_DIR%'; $Shortcut.IconLocation = '%ICON_PATH%'; $Shortcut.Save()"

echo.
echo Success! OmniConv added to startup.
timeout /t 3
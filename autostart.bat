@echo off
set "SCRIPT_DIR=%~dp0"
if not "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR%\"

set "TARGET_VBS=%SCRIPT_DIR%start.vbs"
set "ICON_PATH=%SCRIPT_DIR%app\static\ico.ico"
set "SHORTCUT_NAME=OmniConv.lnk"
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

echo Configuring autostart for OmniConv...

powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$lnk = $ws.CreateShortcut('%STARTUP_FOLDER%\%SHORTCUT_NAME%');" ^
  "$lnk.TargetPath = 'wscript.exe';" ^
  "$lnk.Arguments = '//nologo \""%TARGET_VBS%""\"';" ^
  "$lnk.WorkingDirectory = '%SCRIPT_DIR%';" ^
  "$lnk.IconLocation = '%ICON_PATH%';" ^
  "$lnk.Save()"

echo.
echo Success! OmniConv added to startup.
timeout /t 3
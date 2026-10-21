@echo off
rem ============================================================
rem  wordclip.bat  --  AI answer -> Word-friendly clipboard
rem
rem  Usage:
rem    1) In the AI chat page, press Ctrl+A then Ctrl+C
rem    2) Double-click this file
rem    3) Switch to Word, press Ctrl+V
rem
rem  Why is this file pure ASCII?  cmd.exe parses .bat files with the
rem  OEM code page (GBK on Chinese Windows) regardless of the file's
rem  real encoding.  Any Chinese characters placed BEFORE "chcp 65001"
rem  get decoded as garbage and cmd then tries to run the fragments as
rem  commands ("'xxx' is not recognized...").  So: no CJK in this file.
rem  All Chinese messages are printed by wordclip.ps1, which handles
rem  UTF-8 correctly.
rem ============================================================
chcp 65001 >nul 2>&1
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0wordclip.ps1" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo --------------------------------------------------------
    echo  Failed. Exit code %RC%.
    echo  Copy the messages above and send them to the service owner.
    echo --------------------------------------------------------
    pause
)

endlocal & exit /b %RC%

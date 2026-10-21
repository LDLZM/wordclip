@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title AI 回答转 Word - 一键转换

rem =====================================================================
rem  wordclip.ps1 启动器
rem  作用：读取剪贴板里的 Markdown（例如从 DeepSeek/ChatGPT 页面复制），
rem        转成 Word 富文本格式后写回剪贴板，之后在 Word 里直接 Ctrl+V。
rem  用法：双击运行；或在任意地方选中文字复制后运行。
rem =====================================================================

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0wordclip.ps1" %*
if errorlevel 1 (
  echo.
  echo [转换失败] 请查看上面的提示信息。
  pause
)

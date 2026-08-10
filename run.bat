@echo off
rem InkFlow をコンソールなしで起動する。
rem 引数にプロジェクトファイル・PDFフォルダ・PDFを渡すこともできる（D&D可）。
setlocal
set "HERE=%~dp0"
start "" "%HERE%.venv\Scripts\pythonw.exe" -m inkflow %*
endlocal

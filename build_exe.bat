@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   特征微生物分析工具 - 打包（纯程序）
echo ============================================

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 找不到 .venv，请先创建虚拟环境
    exit /b 1
)

echo.
echo [1/4] 编译界面 (.ui -^> .py)
.venv\Scripts\python.exe tools\build_ui.py
if errorlevel 1 goto :err

echo.
echo [2/4] 打包 exe（约 1 分钟）
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name "特征微生物分析工具" ^
  --icon assets\app.ico ^
  --add-data "assets;assets" ^
  --exclude-module PySide6.QtWebEngineCore ^
  --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.QtPdf ^
  --exclude-module PySide6.QtPdfWidgets ^
  main.py
if errorlevel 1 goto :err

echo.
echo [3/4] 附带知识库索引（只带 pkl，不带 PDF / 说明文档）
if exist "knowledge\index\bm25.pkl" (
    if not exist "dist\特征微生物分析工具\knowledge\index" mkdir "dist\特征微生物分析工具\knowledge\index"
    copy /y "knowledge\index\bm25.pkl" "dist\特征微生物分析工具\knowledge\index\" >nul
    echo        已附带 bm25.pkl
) else (
    echo        [提示] 没找到 knowledge\index\bm25.pkl，本包将不带本地知识库
)

echo.
echo [4/4] 压缩成 zip
if not exist "output" mkdir output
if exist "output\特征微生物分析工具_Demo.zip" del /q "output\特征微生物分析工具_Demo.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\特征微生物分析工具\*' -DestinationPath 'output\特征微生物分析工具_Demo.zip' -Force"
if errorlevel 1 goto :err

echo.
echo ============================================
echo   完成（纯程序，不含说明/测试数据）
echo   exe 目录: dist\特征微生物分析工具\
echo   发布包  : output\特征微生物分析工具_Demo.zip
echo ============================================
exit /b 0

:err
echo.
echo [失败] 打包中断，请查看上面的错误信息
exit /b 1

@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 找不到 .venv，请先创建虚拟环境并安装 requirements.txt
    pause
    exit /b 1
)

if not defined MICROBE_API_DATA_DIR set "MICROBE_API_DATA_DIR=%~dp0data\api"
if not defined MICROBE_API_HOST set "MICROBE_API_HOST=127.0.0.1"
if not defined MICROBE_API_PORT set "MICROBE_API_PORT=8000"

echo ============================================
echo   特征微生物分析工具 - 后端 API
echo ============================================
echo   数据目录: %MICROBE_API_DATA_DIR%
echo   监听地址: http://%MICROBE_API_HOST%:%MICROBE_API_PORT%
echo   接口文档: http://%MICROBE_API_HOST%:%MICROBE_API_PORT%/docs
echo.
if "%MICROBE_API_HOST%"=="0.0.0.0" (
    echo   局域网模式：其他设备请用上面的本机 IPv4 访问。
    if defined MICROBE_API_KEY echo   API Key: %MICROBE_API_KEY%
) else (
    echo   本机测试请用 127.0.0.1；
    echo   同一 WiFi 联调请使用 start_api_lan.bat。
)
echo ============================================
echo.

".venv\Scripts\python.exe" -m server

echo.
echo 服务已退出。
pause

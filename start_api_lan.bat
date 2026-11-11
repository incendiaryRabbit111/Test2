@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 找不到 .venv，请先创建虚拟环境并安装 requirements.txt
    pause
    exit /b 1
)

if not defined MICROBE_API_PORT set "MICROBE_API_PORT=8000"
if not "%~1"=="" set "MICROBE_API_PORT=%~1"
if not defined MICROBE_API_DATA_DIR set "MICROBE_API_DATA_DIR=%~dp0data\api"
set "MICROBE_API_HOST=0.0.0.0"
set "KEY_FILE=%MICROBE_API_DATA_DIR%\lan_api_key.txt"
set "FIREWALL_RULE=MicrobeAnalyzerAPI-%MICROBE_API_PORT%"

echo ============================================
echo   特征微生物分析工具 - 局域网 API
echo ============================================
echo   端口: %MICROBE_API_PORT%
echo   数据目录: %MICROBE_API_DATA_DIR%
echo.

if defined MICROBE_SKIP_FIREWALL goto :after_firewall

net session >nul 2>&1
if errorlevel 1 (
    echo [提示] 添加防火墙规则需要管理员权限，正在请求提权...
    if "%~1"=="" (
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    ) else (
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%~1' -Verb RunAs"
    )
    exit /b
)

netsh advfirewall firewall show rule name="%FIREWALL_RULE%" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="%FIREWALL_RULE%" dir=in action=allow protocol=TCP localport=%MICROBE_API_PORT% profile=private remoteip=localsubnet >nul
    if errorlevel 1 (
        echo [警告] 防火墙规则添加失败，请手动放行 TCP %MICROBE_API_PORT%
    ) else (
        echo [完成] 已添加防火墙规则：%FIREWALL_RULE%（仅专用网络/本子网）
    )
) else (
    echo [完成] 防火墙规则已存在：%FIREWALL_RULE%
)

:after_firewall

if not exist "%MICROBE_API_DATA_DIR%" mkdir "%MICROBE_API_DATA_DIR%" >nul 2>&1

if not defined MICROBE_API_KEY (
    if exist "%KEY_FILE%" (
        for /f "usebackq delims=" %%k in ("%KEY_FILE%") do if not defined MICROBE_API_KEY set "MICROBE_API_KEY=%%k"
    )
)

if not defined MICROBE_API_KEY (
    for /f "usebackq delims=" %%k in (`powershell -NoProfile -Command "[guid]::NewGuid().ToString('N')"`) do set "MICROBE_API_KEY=%%k"
    if defined MICROBE_API_KEY (
        > "%KEY_FILE%" echo !MICROBE_API_KEY!
    )
)

if not defined MICROBE_API_KEY (
    echo [错误] 无法生成 API Key
    pause
    exit /b 1
)

echo.
echo   局域网访问地址（看 InterfaceAlias 里的 Wi-Fi/以太网）：
powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object InterfaceAlias,IPAddress | Format-Table -AutoSize" 2>nul
echo.
echo   客户端请求头：
echo       X-API-Key: %MICROBE_API_KEY%
echo.
echo   注意：
echo   1. Windows 网络需要设置为“专用网络”，否则防火墙规则不生效；
echo   2. 只允许本子网访问，不要对公网做端口映射；
echo   3. 如果 8000 被占用，可运行：start_api_lan.bat 8001
echo ============================================
echo.

call "%~dp0start_api.bat"

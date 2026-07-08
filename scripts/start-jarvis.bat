@echo off
chcp 65001 >nul
echo ========================================
echo   小奕 J.A.R.V.I.S. - Windows 启动器
echo ========================================
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

:: 检查 Ollama
ollama --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Ollama，请先安装 Ollama
    pause
    exit /b 1
)

:: 启动 Ollama 服务（如果未运行）
echo [1/3] 检查 Ollama 服务...
ollama list >nul 2>&1
if errorlevel 1 (
    echo      正在启动 Ollama 服务...
    start "Ollama" ollama serve
    timeout /t 3 /nobreak >nul
)

:: 拉取默认模型
echo [2/3] 检查模型...
ollama list | findstr qwen2.5 >nul 2>&1
if errorlevel 1 (
    echo      正在拉取 qwen2.5:7b 模型（首次运行需要几分钟）...
    ollama pull qwen2.5:7b
) else (
    echo      模型已就绪
)

:: 启动小奕服务
echo [3/3] 启动 J.A.R.V.I.S. API 服务...
echo.
echo   🌐 服务地址：http://localhost:8080
echo   📋 可用端点：
echo      - GET  /api/health
echo      - GET  /api/system/stats
echo      - GET  /api/ollama/status
echo      - GET  /api/ollama/models
echo      - POST /api/ollama/chat
echo      - GET  /api/plugins
echo      - GET  /api/memory/entries
echo      - POST /api/memory/store
echo.
echo   按 Ctrl+C 停止服务
echo ========================================
echo.

python src\main.py

pause

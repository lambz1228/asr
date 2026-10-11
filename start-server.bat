@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0asr-server"

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 Python，请先安装 Python 3.10+ 并加入 PATH
  pause
  exit /b 1
)
for /f "delims=" %%v in ('python --version') do echo [1/4] 使用 %%v

if not exist ".venv" (
  echo [2/4] 创建虚拟环境 .venv ...
  python -m venv .venv
) else (
  echo [2/4] 已存在 .venv，跳过创建
)

echo [3/4] 安装依赖（首次约 1-3 分钟）...
".venv\Scripts\python.exe" -m pip install -q --upgrade pip
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt

if not exist ".env" (
  echo        生成 .env（复制自 .env.example，开发默认值可直接用）
  copy /y ".env.example" ".env" >nul
)

echo [4/4] 启动后端 -^> http://localhost:8000  （按 Ctrl+C 停止）
".venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
pause

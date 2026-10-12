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

rem ============================================================
rem 主机务必保持 0.0.0.0（IPv4），**不要**改成 --host ::**。
rem Windows 上绑定 [::] 不收 IPv4：127.0.0.1 会被直接拒（实测 2039ms），
rem 真机局域网联调也会一起断。而小程序端用的是 127.0.0.1（见 app.ts 的说明），
rem 两边必须都是 IPv4。
rem ============================================================
echo [4/4] 启动后端 -^> http://127.0.0.1:8000  （小程序模拟器也请用 127.0.0.1）
".venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
pause

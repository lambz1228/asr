#!/usr/bin/env bash
# 一键启动 ASR 采集后端（开发模式）
# 用法：在 E:/asr 目录下执行  bash start-server.sh
#      或指定解释器：PYTHON="C:/Program Files/Python312/python.exe" bash start-server.sh
set -e

cd "$(dirname "$0")/asr-server"

# 1) 定位 Python
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  if command -v python3 >/dev/null 2>&1; then PY=python3
  elif command -v python >/dev/null 2>&1; then PY=python
  else echo "[错误] 未找到 Python，请先安装 Python 3.10+ 并加入 PATH"; exit 1; fi
fi
echo "[1/4] 使用 Python: $("$PY" --version 2>&1)"

# 2) 创建虚拟环境
if [ ! -d ".venv" ]; then
  echo "[2/4] 创建虚拟环境 .venv ..."
  "$PY" -m venv .venv
else
  echo "[2/4] 已存在 .venv，跳过创建"
fi

# 3) 安装依赖（首次较慢）
if [ -x ".venv/bin/python" ]; then VPY=".venv/bin/python"; else VPY=".venv/Scripts/python.exe"; fi
echo "[3/4] 安装依赖（首次约 1-3 分钟）..."
"$VPY" -m pip install -q --upgrade pip
"$VPY" -m pip install -q -r requirements.txt

# 4) 生成 .env 并启动
if [ ! -f ".env" ]; then
  echo "       生成 .env（复制自 .env.example，开发默认值可直接用）"
  cp .env.example .env
fi

# 主机务必保持 0.0.0.0（IPv4），**不要**改成 --host ::**。
# Windows 上绑定 [::] 不收 IPv4：127.0.0.1 会被直接拒（实测 2039ms），
# 真机局域网联调也会一起断。而小程序端用的是 127.0.0.1（见 app.ts 的说明），
# 两边必须都是 IPv4。
echo "[4/4] 启动后端 -> http://127.0.0.1:8000  （小程序模拟器也请用 127.0.0.1）"
exec "$VPY" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

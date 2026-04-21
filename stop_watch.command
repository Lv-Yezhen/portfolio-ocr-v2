#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="python3"
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
fi

read_config_paths() {
  "$PYTHON_BIN" - <<'PY'
import os
import yaml

root = os.getcwd()
with open("config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}

md_path = str(cfg.get("holdings_md", "holdings.md"))
if not os.path.isabs(md_path):
    md_path = os.path.join(root, md_path)

md_dir = os.path.dirname(md_path) or root
print(md_dir)
PY
}

MD_DIR="$(read_config_paths)"
PID_FILE="$MD_DIR/.portfolio_ocr_watch.pid"
RUNNING_MARK_FILE="$MD_DIR/portfolio_ocr_watch.running"

if [ ! -f "$PID_FILE" ]; then
  rm -f "$RUNNING_MARK_FILE"
  echo "未找到运行中的 watch（无 PID 文件）"
  exit 0
fi

PID="$(cat "$PID_FILE" 2>/dev/null || true)"
if [ -n "${PID}" ] && kill -0 "$PID" 2>/dev/null; then
  kill "$PID" || true
  sleep 0.5
  if kill -0 "$PID" 2>/dev/null; then
    kill -9 "$PID" || true
  fi
  echo "watch 已停止（PID: $PID）"
else
  echo "PID 不存在或已退出，清理标记文件"
fi

rm -f "$PID_FILE" "$RUNNING_MARK_FILE"

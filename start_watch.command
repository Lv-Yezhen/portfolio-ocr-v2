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
LOG_FILE="$MD_DIR/.portfolio_ocr_watch.log"

mkdir -p "$MD_DIR"

if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${OLD_PID}" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "watch 已在运行（PID: $OLD_PID）"
    touch "$RUNNING_MARK_FILE"
    exit 0
  fi
fi

nohup "$PYTHON_BIN" "$SCRIPT_DIR/main.py" --watch >/dev/null 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"
touch "$RUNNING_MARK_FILE"

echo "watch 已启动（PID: $NEW_PID）"
echo "日志: $LOG_FILE"

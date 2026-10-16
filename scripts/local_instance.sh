#!/usr/bin/env bash
# help-cat · 本地实例（在开发机上真跑一套：FastAPI + H5 静态代理）
#
#   scripts/local_instance.sh up        起（后台，手动用）
#   scripts/local_instance.sh down      停
#   scripts/local_instance.sh status    看状态
#   scripts/local_instance.sh refresh   用服务器最新备份刷新本地数据
#   scripts/local_instance.sh run-api   前台跑 API（给 launchd 托管用，别手动跑）
#   scripts/local_instance.sh run-h5    前台跑 H5（同上）
#
# 与 `dev_preview.py` 手起预览的区别：这是**受管的一套**
#   * 数据固定在 work/local/（gitignore），可用服务器备份一键刷新
#   * 端口固定：API 127.0.0.1:18000（对齐线上）、H5 0.0.0.0:8199（局域网可看）
#   * 交给 launchd 托管（scripts/install_local_launchagents.sh）：开机自启、崩了自动拉起
#
# 端口可覆盖：HELPCAT_LOCAL_API_PORT / HELPCAT_LOCAL_H5_PORT
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_DIR="$ROOT/work/local"
DB="$LOCAL_DIR/help-cat.db"
UPLOADS="$LOCAL_DIR/uploads"
API_PORT="${HELPCAT_LOCAL_API_PORT:-18000}"
H5_PORT="${HELPCAT_LOCAL_H5_PORT:-8199}"
PY="$ROOT/.venv/bin/python"
LOGS="$ROOT/work/local/logs"
API_PID="$LOGS/api.pid"
H5_PID="$LOGS/h5.pid"

say() { printf '%s\n' "$*"; }
die() { printf '✗ %s\n' "$*" >&2; exit 1; }

[ -x "$PY" ] || die "找不到 .venv/bin/python（先建虚拟环境并装依赖）"

ensure_data() {
  if [ -f "$DB" ] && [ -d "$UPLOADS" ]; then return 0; fi
  local src
  src="$(ls -1d "$HOME"/helpcat-backups/*/ 2>/dev/null | sort | tail -1)"
  [ -n "$src" ] || die "本地没有数据，也没有可用备份（$HOME/helpcat-backups）"
  say "首次准备数据，取最新备份：${src%/}"
  mkdir -p "$LOCAL_DIR"
  cp -f "${src}help-cat.db" "$DB" || die "复制数据库失败"
  rm -rf "$UPLOADS"; mkdir -p "$UPLOADS"
  tar xzf "${src}uploads.tar.gz" -C "$LOCAL_DIR" 2>/dev/null || true
  # backups 里的 tar 内含 uploads/ 目录；万一解到别处就兜一下
  [ -d "$UPLOADS" ] || { mkdir -p "$UPLOADS"; tar xzf "${src}uploads.tar.gz" -C "$UPLOADS" 2>/dev/null || true; }
  say "数据就绪：$(ls -1 "$UPLOADS" | wc -l | tr -d ' ') 个上传文件 + $(du -h "$DB" | cut -f1) 数据库"
}

api_env() {
  HELPCAT_DATABASE_URL="sqlite:///$DB" \
  HELPCAT_STORAGE_ROOT="$UPLOADS" \
  PYTHONPYCACHEPREFIX=/tmp/help-cat-local-pycache \
  "$@"
}

run_api() {
  ensure_data
  mkdir -p "$LOGS"
  cd "$ROOT"
  exec env HELPCAT_DATABASE_URL="sqlite:///$DB" HELPCAT_STORAGE_ROOT="$UPLOADS" \
    PYTHONPYCACHEPREFIX=/tmp/help-cat-local-pycache \
    "$PY" -m uvicorn server.helpcat.app:app --host 127.0.0.1 --port "$API_PORT"
}

run_h5() {
  ensure_data
  mkdir -p "$LOGS"
  cd "$ROOT"
  exec "$PY" scripts/dev_preview.py --host 0.0.0.0 --port "$H5_PORT" \
    --api "http://127.0.0.1:$API_PORT"
}

up() {
  ensure_data
  mkdir -p "$LOGS"
  if status >/dev/null 2>&1; then say "已经在跑"; return 0; fi
  nohup bash "$0" run-api >> "$LOGS/api.log" 2>&1 &
  echo $! > "$API_PID"
  nohup bash "$0" run-h5 >> "$LOGS/h5.log" 2>&1 &
  echo $! > "$H5_PID"
  sleep 5
  if status >/dev/null 2>&1; then
    local ip; ip="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo 127.0.0.1)"
    say "本地实例已启动"
    say "  本机   http://127.0.0.1:$H5_PORT/"
    say "  局域网 http://$ip:$H5_PORT/   （手机同一 Wi-Fi；注意关掉手机 VPN）"
  else
    die "启动失败，看 $LOGS/{api,h5}.log"
  fi
}

down() {
  for f in "$API_PID" "$H5_PID"; do
    [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; rm -f "$f"
  done
  pkill -f "uvicorn server.helpcat.app:app --host 127.0.0.1 --port $API_PORT" 2>/dev/null
  pkill -f "dev_preview.py --host 0.0.0.0 --port $H5_PORT" 2>/dev/null
  say "已停止本地实例"
}

status() {
  local ok=0
  if curl -s --noproxy '*' -o /dev/null -m 4 "http://127.0.0.1:$API_PORT/api/v1/cats"; then
    say "API  ✓ http://127.0.0.1:$API_PORT"
  else
    say "API  ✗ 未响应（:${API_PORT}）"; ok=1
  fi
  local code
  code="$(curl -s --noproxy '*' -o /dev/null -m 4 -w '%{http_code}' "http://127.0.0.1:$H5_PORT/" 2>/dev/null)"
  if [ "$code" = "200" ]; then
    say "H5   ✓ http://127.0.0.1:$H5_PORT/  版本 $(curl -s --noproxy '*' -m 4 "http://127.0.0.1:$H5_PORT/version.js" | sed -n 's/.*CURRENT_VERSION *= *"\([^"]*\)".*/\1/p')"
  else
    say "H5   ✗ 未响应（:$H5_PORT → ${code}）"; ok=1
  fi
  return $ok
}

refresh() {
  say "从服务器拉最新备份…"
  ( cd "$ROOT" && bash scripts/pull_backup.sh --latest-only ) || say "  拉取失败（保留现有数据）"
  local src; src="$(ls -1d "$HOME"/helpcat-backups/*/ 2>/dev/null | sort | tail -1)"
  [ -n "$src" ] || die "没有可用备份"
  rm -f "$DB"; rm -rf "$UPLOADS"; mkdir -p "$UPLOADS"
  cp -f "${src}help-cat.db" "$DB"
  tar xzf "${src}uploads.tar.gz" -C "$LOCAL_DIR" 2>/dev/null || tar xzf "${src}uploads.tar.gz" -C "$UPLOADS" 2>/dev/null || true
  say "已刷新到 ${src%/}"
  say "（若在跑，请 scripts/local_instance.sh down && up，或让 launchd 自己拉起）"
}

case "${1:-status}" in
  up) up ;;
  down) down ;;
  status) status ;;
  refresh) refresh ;;
  run-api) run_api ;;
  run-h5) run_h5 ;;
  *) die "用法: local_instance.sh {up|down|status|refresh|run-api|run-h5}" ;;
esac

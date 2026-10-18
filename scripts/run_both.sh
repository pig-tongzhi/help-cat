#!/usr/bin/env bash
# help-cat 本地实例 · 一个进程同时管 API + H5
#
# 背景：原来拆成两个 launchd 任务（com.helpcat.local-api / -h5），
# 现在合并成一个（com.helpcat.local），任一子进程退出就整体退出，
# 由 launchd 的 KeepAlive 把整组重新拉起 —— 两个服务永远同生共死。
#
# 不用 `wait -n`：macOS 自带 bash 3.2 不支持。
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/local_instance.sh"
ROOT="$(cd "$HERE/.." && pwd)"
LOGS="$ROOT/work/local/logs"
mkdir -p "$LOGS"

bash "$S" run-api >> "$LOGS/local-api.log" 2>&1 &
API=$!
bash "$S" run-h5  >> "$LOGS/local-h5.log"  2>&1 &
H5=$!

cleanup() {
  kill "$API" "$H5" 2>/dev/null
  wait "$API" "$H5" 2>/dev/null
}
trap cleanup EXIT TERM INT

# 任一挂掉就整体退出（exit 1 → launchd KeepAlive 重启整组）
while kill -0 "$API" 2>/dev/null && kill -0 "$H5" 2>/dev/null; do
  sleep 5
done
exit 1

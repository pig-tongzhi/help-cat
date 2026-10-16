#!/usr/bin/env bash
# help-cat · 安装/卸载「本地实例」的 LaunchAgent（开发机上跑）
#
#   scripts/install_local_launchagents.sh              # 装（API + H5 两个 agent）
#   scripts/install_local_launchagents.sh --uninstall  # 卸载并停掉
#
# 为什么用两个 agent：一个 agent 只管一个前台进程，崩了各自被 launchd 拉起，
# 日志也分开。plist 由 python plistlib 生成（手拼 XML 漏一个 </array> 就会
# bootstrap 报 "Input/output error"，2026-10-16 在另一个项目上踩过）。
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
SCRIPT="$ROOT/scripts/local_instance.sh"
LABEL_API="com.helpcat.local-api"
LABEL_H5="com.helpcat.local-h5"
LOGS="$ROOT/work/local/logs"
UNINSTALL=0
[ "${1:-}" = "--uninstall" ] && UNINSTALL=1

mkdir -p "$AGENTS" "$LOGS"

write_agent() {
  local label="$1"; shift
  python3 - "$AGENTS" "$label" "$LOGS" "$@" <<'PY'
import plistlib, sys, pathlib
agents, label, logs, *argv = sys.argv[1:]
plist = {
    "Label": label,
    "ProgramArguments": argv,
    "RunAtLoad": True,
    "KeepAlive": True,          # 崩了/被杀就自动拉起
    "ThrottleInterval": 10,
    "StandardOutPath": f"{logs}/{label.split('.')[-1]}.log",
    "StandardErrorPath": f"{logs}/{label.split('.')[-1]}.log",
    "WorkingDirectory": str(pathlib.Path(logs).parent.parent),
}
out = pathlib.Path(agents) / f"{label}.plist"
with open(out, "wb") as fh:
    plistlib.dump(plist, fh)
print(f"  已写 {out}")
PY
  local uid; uid="$(id -u)"
  launchctl bootout "gui/${uid}/${label}" 2>/dev/null || true
  launchctl bootstrap "gui/${uid}" "$AGENTS/${label}.plist" 2>&1 | tail -1 || true
  sleep 2
  if launchctl list 2>/dev/null | grep -q "$label"; then
    echo "  ✓ $label 已加载"
  else
    echo "  ✗ $label 加载失败"; return 1
  fi
}

if [ "$UNINSTALL" = "1" ]; then
  for l in "$LABEL_API" "$LABEL_H5"; do
    launchctl bootout "gui/$(id -u)/$l" 2>/dev/null && echo "  已卸载 $l"
    rm -f "$AGENTS/$l.plist"
  done
  bash "$SCRIPT" down >/dev/null 2>&1 || true
  echo "  完成（本地实例已停）"
  exit 0
fi

echo "① API（127.0.0.1:18000，对齐线上端口）"
write_agent "$LABEL_API" /bin/bash "$SCRIPT" run-api
echo "② H5（0.0.0.0:8199，局域网可看）"
write_agent "$LABEL_H5" /bin/bash "$SCRIPT" run-h5
sleep 4
echo
bash "$SCRIPT" status || true
echo
echo "查看状态：launchctl list | grep helpcat"
echo "卸载：$SCRIPT 同目录的 install_local_launchagents.sh --uninstall"

#!/usr/bin/env bash
#
# 升静态资源版本号（`?v=` / `data-app-version` / `version.js`）。
#
# 为什么必须有这个脚本：`index.html` 是 no-cache，但 CSS/JS/图片是长缓存，
# 改了内容不升版本号，已访问用户会继续跑旧文件 —— 线上已经踩过两次
# 「改了等于没改」。手工漏升过，所以这里把「哪些文件属于哪条版本线」写死。
#
# 用法:
#   scripts/bump_version.sh --next               # 每条版本线各自 +1（…-r4 -> …-r5）
#   scripts/bump_version.sh 20261001-product-r1  # 显式指定主版本号
#   scripts/bump_version.sh --next --dry-run     # 只打印计划，不落盘
#   scripts/bump_version.sh --check              # 校验现存版本号是否自洽（CI 可用）
#
# 版本线:
#   primary  app/rescue/ 与 admin/  —— 取自 app/rescue/version.js 的 CURRENT_VERSION
#   welcome  app/welcome/           —— 取自 app/welcome/index.html 的 data-app-version
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PRIMARY_FILES=(
  app/rescue/index.html
  app/rescue/version.js
  app/rescue/manifest.webmanifest
  admin/index.html
  tests/test_rescue_h5_contract.py
  tests/test_commercial_frontends.py
)
WELCOME_FILES=(
  app/welcome/index.html
)

DRY_RUN=0

usage() {
  sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

primary_current() {
  sed -n 's/.*CURRENT_VERSION *= *"\([^"]*\)".*/\1/p' app/rescue/version.js | head -1
}

welcome_current() {
  sed -n 's/.*data-app-version="\([^"]*\)".*/\1/p' app/welcome/index.html | head -1
}

next_version() {
  # 20260923-product-r4 -> 20260923-product-r5；没有 -rN 后缀就补 -r2
  local version="$1"
  if [[ "$version" =~ ^(.*-r)([0-9]+)$ ]]; then
    printf '%s%s\n' "${BASH_REMATCH[1]}" "$(( BASH_REMATCH[2] + 1 ))"
  else
    printf '%s-r2\n' "$version"
  fi
}

# 同一版本线里出现的版本号种类（应为 1）；顺带证明版本线内部没有漂移。
stream_versions() {
  local file
  for file in "$@"; do
    [ -f "$file" ] || continue
    grep -o -E '[0-9]{8}-[a-z0-9-]+' "$file" || true
  done | sort -u
}

count_in_file() {
  grep -c -F -- "$1" "$2" 2>/dev/null || true
}

replace_in_file() {
  # perl 的 \Q...\E 让替换是纯字面量；BSD/GNU 的 sed -i 语法不一致，所以不用 sed。
  OLD="$1" NEW="$2" perl -pi -e 's/\Q$ENV{OLD}\E/$ENV{NEW}/g' "$3"
}

bump_stream() {
  local label="$1" old="$2" new="$3"
  shift 3
  local file count changed=0
  for file in "$@"; do
    [ -f "$file" ] || continue
    count="$(count_in_file "$old" "$file")"
    [ "$count" -eq 0 ] && continue
    if [ "$DRY_RUN" -eq 0 ]; then
      replace_in_file "$old" "$new" "$file"
    fi
    printf '   %-24s %-42s %s -> %s (%s 处)\n' "$label" "$file" "$old" "$new" "$count"
    changed=$(( changed + 1 ))
  done
  [ "$changed" -gt 0 ] || printf '   %-24s %s\n' "$label" "（没有需要改的文件）"
}

check_stream() {
  local label="$1" declared="$2"
  shift 2
  local found status=0
  found="$(stream_versions "$@")"
  local count
  count="$(printf '%s\n' "$found" | grep -c . || true)"
  if [ "$count" -ne 1 ]; then
    printf '✗ %s 版本线内部不一致，出现 %s 个版本号：\n%s\n' "$label" "$count" "$found"
    status=1
  elif [ "$found" != "$declared" ]; then
    printf '✗ %s 版本号漂移：声明 %s，文件里是 %s\n' "$label" "$declared" "$found"
    status=1
  else
    printf '✓ %-8s %s\n' "$label" "$declared"
  fi
  return "$status"
}

# ---- 参数 ----------------------------------------------------------------

MODE="bump"
NEW_PRIMARY=""
case "${1:-}" in
  --help|-h) usage; exit 0 ;;
  --check) MODE="check"; shift ;;
  --next) NEW_PRIMARY="$(next_version "$(primary_current)")"; shift ;;
  "") usage; exit 2 ;;
  *) NEW_PRIMARY="$1"; shift ;;
esac
[ "${1:-}" = "--dry-run" ] && { DRY_RUN=1; shift; }
[ $# -gt 0 ] && { printf '未知参数：%s\n' "$*" >&2; usage; exit 2; }

CURRENT_PRIMARY="$(primary_current)"
CURRENT_WELCOME="$(welcome_current)"
[ -n "$CURRENT_PRIMARY" ] || { echo "读不到 app/rescue/version.js 的 CURRENT_VERSION" >&2; exit 1; }
[ -n "$CURRENT_WELCOME" ] || { echo "读不到 app/welcome/index.html 的 data-app-version" >&2; exit 1; }

if [ "$MODE" = "check" ]; then
  status=0
  check_stream primary "$CURRENT_PRIMARY" "${PRIMARY_FILES[@]}" || status=1
  check_stream welcome "$CURRENT_WELCOME" "${WELCOME_FILES[@]}" || status=1
  exit "$status"
fi

if [ -z "$NEW_PRIMARY" ]; then
  usage; exit 2
fi
if ! [[ "$NEW_PRIMARY" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  printf '版本号只能是字母数字和 . _ -：%s\n' "$NEW_PRIMARY" >&2
  exit 2
fi
if [ "$NEW_PRIMARY" = "$CURRENT_PRIMARY" ]; then
  printf '新版本号和当前主版本一致（%s），等于没升。用 --next 或换一个。\n' "$NEW_PRIMARY" >&2
  exit 2
fi

NEW_WELCOME="$(next_version "$CURRENT_WELCOME")"

printf '%s\n' "静态资源版本升级${DRY_RUN:+（dry-run，不写文件）}"
bump_stream primary "$CURRENT_PRIMARY" "$NEW_PRIMARY" "${PRIMARY_FILES[@]}"
bump_stream welcome "$CURRENT_WELCOME" "$NEW_WELCOME" "${WELCOME_FILES[@]}"

if [ "$DRY_RUN" -eq 1 ]; then
  printf '\n下一步（去掉 --dry-run 真正执行）：\n  1) python -m pytest tests/test_rescue_h5_contract.py tests/test_commercial_frontends.py -q\n  2) git add -A && git commit\n  3) scripts/build_release.sh 后发布\n'
  exit 0
fi

printf '\n提示：记得在 docs/wiki/变更记录.md 补一条，并跑一遍前端契约测试。\n'

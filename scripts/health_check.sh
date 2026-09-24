#!/usr/bin/env bash
#
# 帮帮小猫探活。三类检查：
#   1. 后端 readiness（带一次真实数据库查询）+ liveness
#   2. 两套静态入口（IP 入口的 /help-cat/... 与域名入口）
#   3. 本机状态（systemd 单元、nginx -t、数据库所在盘剩余空间）——只在服务器上做
#
# 用法:
#   scripts/health_check.sh
#   scripts/health_check.sh --base https://helpcat.xyz --quiet
#   HELPCAT_ALERT_WEBHOOK=https://... HELPCAT_ALERT_WEBHOOK_FORMAT=wecom scripts/health_check.sh
#
# 退出码: 0 = 全部通过；1 = 有失败项（systemd timer 会因此把单元标成 failed，便于
# 在 `systemctl list-timers` / `systemctl --failed` 里一眼看到）。
#
# 环境变量:
#   HELPCAT_BASE_URL             默认 http://175.178.41.19
#   HELPCAT_API_PREFIX           默认 /help-cat-api
#   HELPCAT_ALERT_WEBHOOK        失败时 POST 的地址（不设只记日志）
#   HELPCAT_ALERT_WEBHOOK_FORMAT wecom(默认) | feishu | slack
#   HELPCAT_MIN_FREE_MB          数据库盘最低剩余空间，默认 1024
#   HELPCAT_HEALTH_LOG           默认 /var/log/help-cat/health.log（不可写则跳过）
#
set -uo pipefail

BASE_URL="${HELPCAT_BASE_URL:-http://175.178.41.19}"
API_PREFIX="${HELPCAT_API_PREFIX:-/help-cat-api}"
MIN_FREE_MB="${HELPCAT_MIN_FREE_MB:-1024}"
HEALTH_LOG="${HELPCAT_HEALTH_LOG:-/var/log/help-cat/health.log}"
DB_PATH="${HELPCAT_DB_PATH:-/opt/help-cat/data/help-cat.db}"
TIMEOUT="${HELPCAT_HEALTH_TIMEOUT:-8}"

QUIET=0
while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE_URL="$2"; shift 2 ;;
    --base=*) BASE_URL="${1#*=}"; shift ;;
    --quiet|-q) QUIET=1; shift ;;
    --help|-h) sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf '未知参数：%s\n' "$1" >&2; exit 2 ;;
  esac
done
BASE_URL="${BASE_URL%/}"

FAILURES=""
FAIL_COUNT=0
PASSES=0

say() { [ "$QUIET" -eq 1 ] || printf '%s\n' "$*"; }
pass() { PASSES=$(( PASSES + 1 )); say "✓ $1"; }
fail() {
  FAIL_COUNT=$(( FAIL_COUNT + 1 ))
  # macOS 自带 bash 3.2：空数组在 `set -u` 下展开会报 unbound variable，
  # 所以失败项用字符串积累，不用数组。
  FAILURES="${FAILURES}${FAILURES:+
}- $1"
  say "✗ $1"
}

# ---- HTTP 检查 -----------------------------------------------------------

http_get() {  # -> 打印 "状态码<TAB>正文前 2000 字节"
  curl -sS --max-time "$TIMEOUT" -o /tmp/helpcat-health-body.$$ -w '%{http_code}' "$1" 2>/dev/null
}

check_json_ok() {  # url, 需要的子串, 描述
  local url="$1" needle="$2" label="$3" code body
  code="$(http_get "$url")"
  body="$(head -c 2000 /tmp/helpcat-health-body.$$ 2>/dev/null)"
  rm -f /tmp/helpcat-health-body.$$
  if [ "$code" != "200" ]; then
    fail "$label: HTTP $code ($url)"
    return
  fi
  if [ -n "$needle" ] && ! printf '%s' "$body" | grep -q -- "$needle"; then
    fail "$label: HTTP 200 但正文不含 $needle"
    return
  fi
  pass "$label"
}

check_status_200() {
  local url="$1" label="$2" code
  code="$(curl -sS --max-time "$TIMEOUT" -o /dev/null -w '%{http_code}' "$url" 2>/dev/null)"
  if [ "$code" = "200" ]; then pass "$label"; else fail "$label: HTTP $code ($url)"; fi
}

# 后台已经强制 HTTPS（管理员密码只能在加密链路里出现），所以：
# 页面要能从 HTTPS 取到 200，同时 HTTP 必须 301 过去。
check_admin_https() {
  local base="$1"
  local https_base
  https_base="$(printf '%s' "$base" | sed 's#^http://#https://#')"
  check_status_200 "${https_base}/help-cat/admin/" "后台 HTTPS 可访问"
  local code
  code="$(curl -sS --max-time "$TIMEOUT" -o /dev/null -w '%{http_code}' "${base}/help-cat/admin/" 2>/dev/null)"
  if [ "$code" = "301" ] || [ "$code" = "302" ]; then
    pass "后台 HTTP 会跳到 HTTPS"
  else
    fail "后台 HTTP 没有跳 HTTPS（HTTP ${code}）—— 管理员密码可能被明文传输"
  fi
}

# 关键静态素材：发布漏打包一张图时，页面不会报错，只是"照片不显示" —— 线上真踩过
# （换 77 故事第 6 章的照片时漏了一张未跟踪的 webp）。所以逐个探一遍，并要求
# Content-Type 确实是图片/样式/脚本，而不是被 SPA 回退成的 index.html。
check_asset() {
  local url="$1" label="$2" expected="$3" headers code type
  headers="$(curl -sS --max-time "$TIMEOUT" -o /dev/null -D - -w '\n%{http_code}' "$url" 2>/dev/null)"
  code="$(printf '%s' "$headers" | tail -1)"
  type="$(printf '%s' "$headers" | tr -d '\r' | awk 'tolower($1) == "content-type:" {print $2}' | tail -1)"
  if [ "$code" != "200" ]; then
    fail "$label: HTTP $code ($url)"
    return
  fi
  case "$type" in
    $expected) pass "$label" ;;
    *) fail "$label: Content-Type 是 ${type}，期望 ${expected}（是不是回退成了 HTML？）" ;;
  esac
}

check_static_assets() {
  local base="$1" prefix="$2"
  check_asset "$base$prefix/assets/77/cat-cutout.webp" "$prefix 首页主图(77 抠像)" "image/*"
  check_asset "$base$prefix/assets/scenery/meadow-far.svg" "$prefix 草坪远景" "image/svg*"
  check_asset "$base$prefix/assets/scenery/meadow-near.svg" "$prefix 草坪近景" "image/svg*"
  check_asset "$base$prefix/assets/77/rescue-day.webp" "$prefix 77故事·初见" "image/*"
  check_asset "$base$prefix/assets/77/grown-up.webp" "$prefix 77故事·长大" "image/*"
  check_asset "$base$prefix/assets/77/portrait.webp" "$prefix 77故事·正脸" "image/*"
  check_asset "$base$prefix/assets/brand/favicon.svg" "$prefix 站点图标" "image/*"
  check_asset "$base$prefix/styles.css" "$prefix 样式表" "text/css*"
  check_asset "$base$prefix/story-77.js" "$prefix 77故事脚本" "*javascript*"
}

# IP 证书用的是 Let's Encrypt 的 shortlived 配置，只有 6 天。续期一旦没跑起来，
# 浏览器会直接拦下后台登录 —— 必须体检能提前发现，而不是等用户报错。
# 用 openssl 的 -checkend 判断，避免在 macOS/Linux 上做日期差（两边的 date 不一样）。
check_https_cert() {
  local host="$1" label="$2" min_days="${3:-2}"
  if ! command -v openssl >/dev/null 2>&1; then
    say "· 跳过 ${label}（本机没有 openssl）"
    return
  fi
  local pem
  pem="$(echo | openssl s_client -connect "${host}:443" 2>/dev/null | openssl x509 2>/dev/null)"
  if [ -z "$pem" ]; then
    fail "$label: 443 上取不到证书（HTTPS 掉了？）"
    return
  fi
  if printf '%s' "$pem" | openssl x509 -checkend $((min_days * 86400)) -noout >/dev/null 2>&1; then
    pass "${label}（剩余超过 ${min_days} 天）"
  else
    fail "$label: 证书在 ${min_days} 天内过期，续期可能没跑起来"
  fi
}

# 只跑 HTTP 的测试夹具专用（生产不要设）：跳过 HTTPS 相关检查。
HTTP_ONLY="${HELPCAT_HEALTH_HTTP_ONLY:-0}"

say "帮帮小猫探活 $(date '+%F %T')  base=$BASE_URL"

check_json_ok "$BASE_URL$API_PREFIX/api/v1/health" '"status": *"ok"' "后端 liveness"
# readiness 会真查一次库；带数据库故障时这里必须是 503 而不是 200。
check_json_ok "$BASE_URL$API_PREFIX/api/v1/health/ready" '"database": *"ok"' "后端 readiness（含数据库）"
check_status_200 "$BASE_URL/help-cat/rescue/index.html" "IP 入口 H5"
if [ "$HTTP_ONLY" = "1" ]; then
  say "· 跳过 HTTPS 检查（HELPCAT_HEALTH_HTTP_ONLY=1，仅测试夹具用）"
else
  check_admin_https "$BASE_URL"
fi
check_status_200 "$BASE_URL/help-cat/welcome/" "IP 入口欢迎页"
# 两个入口都提供 /help-cat/rescue/... 这份 alias，所以同一组路径两边都能探。
check_static_assets "$BASE_URL" "/help-cat/rescue"
if [ "$HTTP_ONLY" != "1" ]; then
  check_status_200 "$(printf '%s' "$BASE_URL" | sed 's#^http://#https://#')/help-cat/rescue/" "IP 入口 H5（HTTPS）"
fi

# HTTPS 证书（IP 证书 6 天有效，这一条是续期的兜底监控）
HTTPS_HOST="$(printf '%s' "$BASE_URL" | sed -e 's#^https*://##' -e 's#/.*$##' -e 's#:.*$##')"
if [ -n "$HTTPS_HOST" ] && [ "$HTTP_ONLY" != "1" ]; then
  check_https_cert "${HTTPS_HOST}" "HTTPS 证书（${HTTPS_HOST}）"
fi

# 域名入口：ICP 备案没下来之前解析会被拦，所以默认只告警不计数都难，这里只在
# 显式换 base 时才检查，避免每天固定误报。
if [ "$BASE_URL" != "http://175.178.41.19" ]; then
  check_status_200 "$BASE_URL/" "域名入口欢迎页（站点根）"
  check_status_200 "$BASE_URL/rescue/index.html" "域名入口 H5"
  check_status_200 "$BASE_URL/admin/" "域名入口后台"
  check_static_assets "$BASE_URL" "/rescue"
fi

# ---- 本机检查（只在服务器上有意义） --------------------------------------

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files help-cat.service >/dev/null 2>&1; then
  if [ "$(systemctl is-active help-cat.service 2>/dev/null)" = "active" ]; then
    pass "systemd help-cat.service active"
  else
    fail "systemd help-cat.service 不是 active"
  fi
  if command -v nginx >/dev/null 2>&1; then
    if nginx -t >/dev/null 2>&1; then pass "nginx -t 通过"; else fail "nginx -t 失败"; fi
  fi
  if [ -f "$DB_PATH" ]; then
    mount_point="$(df -Pk "$DB_PATH" | awk 'NR==2 {print $6}')"
    free_mb="$(df -Pm "$DB_PATH" | awk 'NR==2 {print $4}')"
    if [ "${free_mb:-0}" -ge "$MIN_FREE_MB" ]; then
      pass "数据库盘剩余 ${free_mb}MB（${mount_point}，阈值 ${MIN_FREE_MB}MB）"
    else
      fail "数据库盘只剩 ${free_mb}MB（${mount_point}，阈值 ${MIN_FREE_MB}MB）"
    fi
  fi
else
  say "· 跳过本机检查（没有 systemctl/help-cat.service，应该是开发机）"
fi

# ---- 输出 / 告警 ---------------------------------------------------------

SUMMARY="帮帮小猫探活：通过 $PASSES 项"
if [ "$FAIL_COUNT" -gt 0 ]; then
  SUMMARY="${SUMMARY}，失败 $FAIL_COUNT 项
$FAILURES"
fi
say "$SUMMARY"

if mkdir -p "$(dirname "$HEALTH_LOG")" 2>/dev/null; then
  printf '%s %s\n' "$(date '+%F %T')" "$(printf '%s' "$SUMMARY" | tr '\n' ' ')" >> "$HEALTH_LOG" 2>/dev/null || true
fi

if [ "$FAIL_COUNT" -gt 0 ] && [ -n "${HELPCAT_ALERT_WEBHOOK:-}" ]; then
  escaped="$(printf '%s' "$SUMMARY" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr '\n' ' ')"
  case "${HELPCAT_ALERT_WEBHOOK_FORMAT:-wecom}" in
    feishu) payload="{\"msg_type\":\"text\",\"content\":{\"text\":\"$escaped\"}}" ;;
    slack|discord|text) payload="{\"text\":\"$escaped\"}" ;;
    *) payload="{\"msgtype\":\"text\",\"text\":{\"content\":\"$escaped\"}}" ;;
  esac
  if curl -sS --max-time "$TIMEOUT" -X POST -H 'Content-Type: application/json' \
      -d "$payload" "$HELPCAT_ALERT_WEBHOOK" >/dev/null 2>&1; then
    say "· 已发出告警"
  else
    say "· 告警发送失败（webhook 不可达）"
  fi
fi

[ "$FAIL_COUNT" -eq 0 ]

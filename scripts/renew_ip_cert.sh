#!/bin/bash
# 续期 help-cat 的 IP 证书（Let's Encrypt shortlived 档案，只有 6 天有效期）。
#
# 为什么不能只靠 `certbot renew`：
#   1. 6 天的证书续期窗口很窄，靠 certbot 自己的"是否到期"判断曾经出现过
#      到期前 2 小时仍然报 "Certificate not yet due for renewal; no action taken"，
#      结果证书过期 —— 微信内置浏览器拒绝过期证书，后台直接打不开，
#      而请求只走到 nginx 的 http→https 跳转，日志里全是 301，很难看出是证书问题。
#   2. certbot 非交互续期默认会随机等待最多 8 分钟（实测 random delay of 383s），
#      人工在终端跑会以为卡死。这里显式关掉。
#
# 所以这个脚本自己算剩余时间：少于 FORCE_DAYS 天就强制续期，并复用监控的
# webhook 在续期失败时告警，避免"过期了没人知道"。
set -u

LINEAGE="175.178.41.19"
CONF_DIR="${HELPCAT_CERT_CONF_DIR:-/etc/letsencrypt}"
CERT="${HELPCAT_CERT_FILE:-$CONF_DIR/live/$LINEAGE/cert.pem}"
CERTBOT="${HELPCAT_CERTBOT:-/opt/certbot-venv/bin/certbot}"
FORCE_DAYS="${HELPCAT_CERT_FORCE_DAYS:-3}"
WARN_HOURS="${HELPCAT_CERT_WARN_HOURS:-24}"
LOG="${HELPCAT_CERT_LOG:-/var/log/helpcat-cert-renew.log}"
ENV_FILE="${HELPCAT_CERT_ENV_FILE:-/etc/help-cat/healthcheck.env}"
HOOK="${HELPCAT_CERT_HOOK:-systemctl reload nginx}"

log() { printf '%s %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG"; }

# 用 openssl 的 -checkend 判断剩余时间，不做日期差：GNU 才有 `date -d`，
# 开发机（macOS）没有，而这个脚本在两边都要能跑（测试就是在本机跑的）。
# -checkend N 的退出码：0 = 至少还能用 N 秒，1 = 会在 N 秒内过期。
expires_within() { ! openssl x509 -checkend "$1" -noout -in "$CERT" >/dev/null 2>&1; }

# 完整的剩余天数（不足一天算 0，已过期算 -1），只用于日志和阈值判断
full_days_left() {
  local d
  for d in 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 20 25 30; do
    if expires_within $(( d * 86400 )); then
      echo $(( d - 1 ))
      return
    fi
  done
  echo 30
}

# 告警复用监控那套 webhook 配置（同一个文件，不额外存密钥）
alert() {
  [ -r "$ENV_FILE" ] || return 0
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  [ -n "${HELPCAT_ALERT_WEBHOOK:-}" ] || return 0
  local text payload
  text="帮帮小猫：IP 证书续期异常。$*"
  case "${HELPCAT_ALERT_WEBHOOK_FORMAT:-wecom}" in
    feishu) payload="{\"msg_type\":\"text\",\"content\":{\"text\":\"$text\"}}" ;;
    slack|discord|text) payload="{\"text\":\"$text\"}" ;;
    *) payload="{\"msgtype\":\"text\",\"text\":{\"content\":\"$text\"}}" ;;
  esac
  curl -sS --max-time 10 -X POST -H 'Content-Type: application/json' -d "$payload" "$HELPCAT_ALERT_WEBHOOK" >/dev/null 2>&1 \
    && log "已发出告警" || log "告警发送失败"
}

[ -r "$CERT" ] || { log "找不到证书 ${CERT}，无法判断是否续期"; alert "找不到证书文件 ${CERT}"; exit 1; }

DAYS_LEFT="$(full_days_left)"
EXPIRES_AT="$(openssl x509 -enddate -noout -in "$CERT" 2>/dev/null | cut -d= -f2)"
log "续期前：到期时间 ${EXPIRES_AT}，剩余约 ${DAYS_LEFT} 天"

if expires_within 0; then
  log "证书已经过期，强制续期"
  FORCE="--force-renewal"
elif expires_within $(( FORCE_DAYS * 86400 )); then
  log "剩余不足 ${FORCE_DAYS} 天，强制续期（不依赖 certbot 自己的到期判断）"
  FORCE="--force-renewal"
else
  log "剩余 ${DAYS_LEFT} 天，按 ARI 常规续期"
  FORCE=""
fi

# 已过期或临近到期才强制；否则走 ARI 常规续期（Let's Encrypt 会建议合适的续期时间）
# --no-random-sleep-on-renew：不要让定时任务随机睡 8 分钟，日志和手动执行都难判断。
if ! "$CERTBOT" renew --cert-name "$LINEAGE" $FORCE \
      --no-random-sleep-on-renew --non-interactive \
      --deploy-hook "$HOOK" >>"$LOG" 2>&1; then
  log "certbot 返回失败，见 $LOG"
  alert "certbot 续期失败（证书剩余 ${DAYS_LEFT} 天），详见服务器 $LOG"
  exit 1
fi

AFTER_DAYS="$(full_days_left)"
log "续期后：剩余约 ${AFTER_DAYS} 天"

# 续期"成功"但时间没往前走，说明拿到的还是旧证书 —— 也要喊出来
if expires_within 0; then
  alert "续期后证书仍然过期，后台 HTTPS 会不可用"
  exit 1
fi
if expires_within $(( WARN_HOURS * 3600 )); then
  alert "续期后证书只剩不到 $(( WARN_HOURS / 24 )) 天，请人工检查续期通道"
  exit 1
fi

log "完成"

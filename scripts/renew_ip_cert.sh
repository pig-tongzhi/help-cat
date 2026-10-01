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
CONF_DIR="/etc/letsencrypt"
CERT="$CONF_DIR/live/$LINEAGE/cert.pem"
CERTBOT="/opt/certbot-venv/bin/certbot"
FORCE_DAYS="${HELPCAT_CERT_FORCE_DAYS:-3}"
WARN_HOURS="${HELPCAT_CERT_WARN_HOURS:-24}"
LOG="/var/log/helpcat-cert-renew.log"
ENV_FILE="/etc/help-cat/healthcheck.env"
HOOK="systemctl reload nginx"

log() { printf '%s %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG"; }

remaining_seconds() {
  local end
  end="$(openssl x509 -enddate -noout -in "$CERT" 2>/dev/null | cut -d= -f2)"
  [ -n "$end" ] || { echo 0; return; }
  echo $(( $(date -d "$end" +%s) - $(date +%s) ))
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

BEFORE="$(remaining_seconds)"
DAYS_LEFT=$(( BEFORE / 86400 ))
HOURS_LEFT=$(( BEFORE / 3600 ))
log "续期前：剩余 ${HOURS_LEFT} 小时（${DAYS_LEFT} 天）"

if [ "$BEFORE" -le 0 ]; then
  log "证书已经过期，强制续期"
  FORCE="--force-renewal"
elif [ "$BEFORE" -le $(( FORCE_DAYS * 86400 )) ]; then
  log "剩余不足 ${FORCE_DAYS} 天，强制续期（不依赖 certbot 自己的到期判断）"
  FORCE="--force-renewal"
else
  FORCE=""
fi

# 已过期或临近到期才强制；否则走 ARI 常规续期（Let's Encrypt 会建议合适的续期时间）
# --no-random-sleep-on-renew：不要让定时任务随机睡 8 分钟，日志和手动执行都难判断。
if ! "$CERTBOT" renew --cert-name "$LINEAGE" $FORCE \
      --no-random-sleep-on-renew --non-interactive \
      --deploy-hook "$HOOK" >>"$LOG" 2>&1; then
  log "certbot 返回失败，见 $LOG"
  alert "certbot 续期失败（证书剩余 ${HOURS_LEFT} 小时），详见服务器 $LOG"
  exit 1
fi

AFTER="$(remaining_seconds)"
log "续期后：剩余 $(( AFTER / 3600 )) 小时（$(( AFTER / 86400 )) 天）"

# 续期"成功"但时间没往前走，说明拿到的还是旧证书 —— 也要喊出来
if [ "$AFTER" -le 0 ]; then
  alert "续期后证书仍然过期，后台 HTTPS 会不可用"
  exit 1
fi
if [ "$AFTER" -le $(( WARN_HOURS * 3600 )); then
  alert "续期后证书只剩 $(( AFTER / 3600 )) 小时，请人工检查续期通道"
  exit 1
fi

log "完成"

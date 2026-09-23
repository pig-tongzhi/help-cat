#!/usr/bin/env bash
#
# 在**开发机**上跑（不是服务器上）：把服务器上最近一次通过自检的备份拉到本地，
# 作为「那台机器整个挂掉也能恢复」的那一份。
#
# 为什么需要它：线上只有一台机器，数据库、上传目录和备份全在同一个盘上
# （`df` 只有 /dev/vda1）。磁盘故障、误删目录、机器被回收，三者一起没。
# 服务器上的 `backup_offsite.sh` 负责把备份做对；这个脚本负责把它挪出那台机器。
#
# 用法:
#   scripts/pull_backup.sh
#   scripts/pull_backup.sh --dest ~/helpcat-backups --keep 14
#   scripts/pull_backup.sh --latest-only --dry-run
#
# 环境变量:
#   HELPCAT_SERVER   默认 root@175.178.41.19
#   HELPCAT_SSH_KEY  默认 ~/.ssh/ajv_purchase_deploy
#   HELPCAT_DEST     默认 ~/helpcat-backups
#
# 注意：拉下来的 `help-cat.db` 是**生产数据**（含用户 openid 与留言联系方式），
# 落在开发机磁盘上。别放进任何 git 仓库、别放到共享目录。
#
set -euo pipefail

SERVER="${HELPCAT_SERVER:-root@175.178.41.19}"
SSH_KEY="${HELPCAT_SSH_KEY:-$HOME/.ssh/ajv_purchase_deploy}"
DEST="${HELPCAT_DEST:-$HOME/helpcat-backups}"
KEEP="${HELPCAT_DEST_KEEP:-14}"
REMOTE_BACKUP_DIR="${HELPCAT_BACKUP_DIR:-/opt/help-cat/backups}"
REMOTE_TOOL="${HELPCAT_REMOTE_TOOL:-/opt/help-cat/current/scripts/backup_offsite.sh}"

DRY_RUN=0
LATEST_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dest) DEST="$2"; shift 2 ;;
    --dest=*) DEST="${1#*=}"; shift ;;
    --keep) KEEP="$2"; shift 2 ;;
    --keep=*) KEEP="${1#*=}"; shift ;;
    --latest-only) LATEST_ONLY=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --help|-h) sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf '未知参数：%s\n' "$1" >&2; exit 2 ;;
  esac
done

# 只认带 SHA256SUMS 的目录：备份目录里还混着历史手工备份（*.db、*.conf），
# 那些没有自检清单，不该被当成可信副本。
remote_newest() {
  ssh -i "$SSH_KEY" -o BatchMode=yes "$SERVER" \
    "for d in \$(ls -1d $REMOTE_BACKUP_DIR/20*/ 2>/dev/null | sort -r); do
       [ -f \"\$d/SHA256SUMS\" ] && { basename \"\$d\"; break; }
     done"
}

remote_verify() {
  ssh -i "$SSH_KEY" -o BatchMode=yes "$SERVER" \
    "$REMOTE_TOOL --verify $REMOTE_BACKUP_DIR/$1 --quiet"
}

remote_size() {
  ssh -i "$SSH_KEY" -o BatchMode=yes "$SERVER" "du -sh $REMOTE_BACKUP_DIR/$1 | cut -f1"
}

STAMP="$(remote_newest)"
[ -n "$STAMP" ] || { echo "服务器 $REMOTE_BACKUP_DIR 下没有带 SHA256SUMS 的备份" >&2; exit 1; }
SIZE="$(remote_size "$STAMP")"

echo "服务器: $SERVER"
echo "最新备份: $STAMP ($SIZE)"
echo "本地目录: $DEST"

if [ "$LATEST_ONLY" -eq 1 ] && [ -d "$DEST/$STAMP" ]; then
  echo "· 本地已存在 ${STAMP}，跳过"
  exit 0
fi

# 先让服务器自己证明这份备份能恢复，再把字节拉过来；反过来会出现
# 「本地有一份看着完整、其实坏了」的副本。
if [ "$DRY_RUN" -eq 0 ]; then
  echo "· 先在服务器上自检…"
  remote_verify "$STAMP"
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "会执行: rsync $SERVER:$REMOTE_BACKUP_DIR/$STAMP/ -> $DEST/$STAMP/"
  echo "会执行: shasum -a 256 -c SHA256SUMS（本地再验一次）"
  echo "会执行: 只保留最近 $KEEP 份"
  exit 0
fi

mkdir -p "$DEST"
rsync -az --exclude '._*' -e "ssh -i $SSH_KEY -o BatchMode=yes" \
  "$SERVER:$REMOTE_BACKUP_DIR/$STAMP/" "$DEST/$STAMP/"

# 本地二次校验：传输过程坏了要在这里暴露，而不是等到真恢复那天。
if command -v shasum >/dev/null 2>&1; then
  ( cd "$DEST/$STAMP" && shasum -a 256 -c SHA256SUMS >/dev/null )
elif command -v sha256sum >/dev/null 2>&1; then
  ( cd "$DEST/$STAMP" && sha256sum -c SHA256SUMS --quiet )
else
  echo "⚠ 本机没有 shasum/sha256sum，跳过本地校验" >&2
fi

PRUNED=0
while IFS= read -r old; do
  [ -n "$old" ] || continue
  rm -rf "$old" && PRUNED=$(( PRUNED + 1 ))
done < <(ls -1d "$DEST"/20*/ 2>/dev/null | sort -r | tail -n "+$(( KEEP + 1 ))")
[ "$PRUNED" -gt 0 ] && echo "· 清理本地旧副本：$PRUNED 份"

COUNT="$(ls -1d "$DEST"/20*/ 2>/dev/null | wc -l | tr -d ' ')"
TOTAL="$(du -sh "$DEST" | cut -f1)"
echo "✓ 已拉取 ${STAMP}，本地现有 ${COUNT} 份副本，合计 ${TOTAL}"
echo
echo "提醒：这一份在开发机磁盘上，仍然怕这台机器坏。真正稳的做法是再放一份到"
echo "异地（对象存储，或私有仓库的加密备份），见 docs/wiki/部署回滚与运维.md。"
echo "另外这份 help-cat.db 是生产数据，别提交进任何 git 仓库。"

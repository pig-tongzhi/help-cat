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

# 本地校验：SHA256SUMS 里列的文件必须都在、且哈希对得上。
# 2026-10-07 那份就是在这里暴露的：目录存在、SHA256SUMS 在，但 uploads.tar.gz 没拉下来，
# 只看目录会以为"备份好好的"，真去恢复才发现少了图片。
local_verify() {
  local dir="$1"
  [ -f "$dir/SHA256SUMS" ] || return 1
  if command -v shasum >/dev/null 2>&1; then
    ( cd "$dir" && shasum -a 256 -c SHA256SUMS >/dev/null 2>&1 )
  elif command -v sha256sum >/dev/null 2>&1; then
    ( cd "$dir" && sha256sum -c SHA256SUMS --quiet >/dev/null 2>&1 )
  else
    return 0   # 本机没有校验工具时不要误判成"坏"
  fi
}

# 拉一份快照到 $DEST/<时间戳>：先落临时目录，本地校验通过才改名就位。
# 这样"拉了一半断掉"只会留下一个 .incoming-* 临时目录，不会伪装成一份可用备份。
fetch_snapshot() {
  # 注意：`local a="$1" b="...$a"` 在同一行里 $a 取的是**外层**的值（set -u 下会直接报未绑定），
  # 所以这里分两行写。
  local stamp="$1"
  local incoming="$DEST/.incoming-$stamp"
  rm -rf "$incoming"
  mkdir -p "$incoming"
  if ! rsync -az --exclude '._*' -e "ssh -i $SSH_KEY -o BatchMode=yes" \
        "$SERVER:$REMOTE_BACKUP_DIR/$stamp/" "$incoming/"; then
    rm -rf "$incoming"
    echo "✗ ${stamp} 下载中断，已丢弃半个副本" >&2
    return 1
  fi
  if ! local_verify "$incoming"; then
    rm -rf "$incoming"
    echo "✗ ${stamp} 本地校验不过，已丢弃这份下载" >&2
    return 1
  fi
  rm -rf "$DEST/$stamp"
  mv "$incoming" "$DEST/$stamp"
}

STAMP="$(remote_newest)"
[ -n "$STAMP" ] || { echo "服务器 $REMOTE_BACKUP_DIR 下没有带 SHA256SUMS 的备份" >&2; exit 1; }
SIZE="$(remote_size "$STAMP")"

echo "服务器: $SERVER"
echo "最新备份: $STAMP ($SIZE)"
echo "本地目录: $DEST"

mkdir -p "$DEST"
# 上次被打断（比如机器睡眠）留下的临时目录，每轮开头清掉
rm -rf "$DEST"/.incoming-* 2>/dev/null || true

if [ "$LATEST_ONLY" -eq 1 ] && [ -d "$DEST/$STAMP" ] && local_verify "$DEST/$STAMP"; then
  echo "· 本地已存在且完整的 ${STAMP}，跳过"
  exit 0
fi

# 先让服务器自己证明这份备份能恢复，再把字节拉过来；反过来会出现
# 「本地有一份看着完整、其实坏了」的副本。
if [ "$DRY_RUN" -eq 0 ]; then
  echo "· 先在服务器上自检…"
  remote_verify "$STAMP"
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "会执行: rsync $SERVER:$REMOTE_BACKUP_DIR/$STAMP/ -> $DEST/.incoming-$STAMP/ 再改名就位"
  echo "会执行: shasum -a 256 -c SHA256SUMS（本地再验一次）"
  echo "会执行: 只保留最近 $KEEP 份，并体检全部本地副本"
  exit 0
fi

fetch_snapshot "$STAMP"

PRUNED=0
while IFS= read -r old; do
  [ -n "$old" ] || continue
  rm -rf "$old" && PRUNED=$(( PRUNED + 1 ))
done < <(ls -1d "$DEST"/20*/ 2>/dev/null | sort -r | tail -n "+$(( KEEP + 1 ))")
[ "$PRUNED" -gt 0 ] && echo "· 清理本地旧副本：$PRUNED 份"

# 收尾体检：脚本只拉最新那份，所以"以前留下的一份坏副本"永远不会被自动碰到。
# 这里把手上所有副本过一遍，坏的当场从服务器重拉；重拉不回来就以失败退出，
# 让 launchd 把这次任务记成 failed，而不是安静地留着一份恢复不了的备份。
BROKEN=0
for dir in $(ls -1d "$DEST"/20*/ 2>/dev/null | sort -r); do
  local_verify "$dir" && continue
  stamp="$(basename "$dir")"
  echo "⚠ 本地 ${stamp} 不完整，尝试从服务器重拉" >&2
  if remote_verify "$stamp" >/dev/null 2>&1 && fetch_snapshot "$stamp"; then
    echo "· ${stamp} 已修复"
  else
    echo "✗ ${stamp} 修不了（服务器上已没有或它自己也没通过自检）" >&2
    BROKEN=$(( BROKEN + 1 ))
  fi
done

COUNT="$(ls -1d "$DEST"/20*/ 2>/dev/null | wc -l | tr -d ' ')"
TOTAL="$(du -sh "$DEST" | cut -f1)"
echo "✓ 已拉取 ${STAMP}，本地现有 ${COUNT} 份副本（全部通过校验），合计 ${TOTAL}"
echo
echo "提醒：这一份在开发机磁盘上，仍然怕这台机器坏。真正稳的做法是再放一份到"
echo "异地（对象存储，或私有仓库的加密备份），见 docs/wiki/部署回滚与运维.md。"
echo "另外这份 help-cat.db 是生产数据，别提交进任何 git 仓库。"

if [ "$BROKEN" -gt 0 ]; then
  echo "✗ 有 ${BROKEN} 份本地副本不完整，需要人工处理" >&2
  exit 1
fi

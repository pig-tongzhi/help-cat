#!/usr/bin/env bash
#
# 帮帮小猫备份。原来只有「同盘目录拷贝」，磁盘故障等于数据+站点一起丢；这个脚本
# 负责把数据库做出一致性快照、打包上传目录、校验、按保留周期清理，并尽量推到异地。
#
# 用法:
#   scripts/backup_offsite.sh                  # 备份一次
#   scripts/backup_offsite.sh --quiet           # 只留告警和错误（systemd 单元用）
#   scripts/backup_offsite.sh --dry-run        # 只说会做什么
#   scripts/backup_offsite.sh --verify latest  # 校验最近的备份能不能恢复
#   scripts/backup_offsite.sh --verify /opt/help-cat/backups/20260924-032000
#
# 环境变量:
#   HELPCAT_DB_PATH              默认 /opt/help-cat/data/help-cat.db
#   HELPCAT_UPLOADS_DIR          默认 /opt/help-cat/data/uploads
#   HELPCAT_BACKUP_DIR           默认 /opt/help-cat/backups
#   HELPCAT_BACKUP_KEEP_DAYS     默认 14
#   HELPCAT_BACKUP_RCLONE_REMOTE 例 cos:help-cat-backup       （有 rclone 时用）
#   HELPCAT_BACKUP_COSCMD_BUCKET 例 help-cat-1300000000       （有 coscmd 时用）
#   HELPCAT_BACKUP_S3_URL        例 s3://help-cat-backup      （有 aws 时用）
#   HELPCAT_BACKUP_UPLOAD_CMD    自定义上传命令，参数是备份目录
#
# 退出码: 0 = 本地备份完成（未配置异地目标只告警）；1 = 快照/校验失败；2 = 参数错误。
#
set -uo pipefail

DB_PATH="${HELPCAT_DB_PATH:-/opt/help-cat/data/help-cat.db}"
UPLOADS_DIR="${HELPCAT_UPLOADS_DIR:-/opt/help-cat/data/uploads}"
BACKUP_DIR="${HELPCAT_BACKUP_DIR:-/opt/help-cat/backups}"
KEEP_DAYS="${HELPCAT_BACKUP_KEEP_DAYS:-14}"
RELEASE_LINK="${HELPCAT_RELEASE_LINK:-/opt/help-cat/current}"

DRY_RUN=0
QUIET=0
MODE="backup"
VERIFY_TARGET=""

while [ $# -gt 0 ]; do
  case "$1" in
    --quiet|-q) QUIET=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --verify) MODE="verify"; VERIFY_TARGET="${2:-latest}"; shift 2 ;;
    --verify=*) MODE="verify"; VERIFY_TARGET="${1#*=}"; shift ;;
    --help|-h) sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf '未知参数：%s\n' "$1" >&2; exit 2 ;;
  esac
done

say() { [ "$QUIET" -eq 1 ] || printf '%s\n' "$*"; }

# 优先用部署环境的解释器：它一定带 sqlite3 模块，且和线上版本一致。
PYTHON="${HELPCAT_PYTHON:-}"
if [ -z "$PYTHON" ]; then
  if [ -x /opt/help-cat/venv/bin/python ]; then PYTHON=/opt/help-cat/venv/bin/python; else PYTHON=python3; fi
fi
[ "$DRY_RUN" -eq 1 ] || command -v "$PYTHON" >/dev/null 2>&1 || { echo "找不到解释器：$PYTHON" >&2; exit 1; }

# ---- 校验模式 -------------------------------------------------------------

verify_backup() {
  local target="$1" status=0
  if [ ! -d "$target" ]; then
    printf '备份目录不存在：%s\n' "$target" >&2
    return 1
  fi
  say "校验 $target"

  if [ -f "$target/SHA256SUMS" ]; then
    if (cd "$target" && sha256sum -c --quiet SHA256SUMS 2>/dev/null || shasum -a 256 -c SHA256SUMS >/dev/null 2>&1); then
      say "✓ 校验和一致"
    else
      printf '✗ 校验和不一致（备份可能损坏）\n'; status=1
    fi
  else
    printf '✗ 缺 SHA256SUMS\n'; status=1
  fi

  if [ -f "$target/help-cat.db" ]; then
    "$PYTHON" - "$target/help-cat.db" <<'PY'
import sqlite3, sys
path = sys.argv[1]
connection = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
if integrity != "ok":
    print("✗ integrity_check: %s" % integrity); sys.exit(1)
counts = {}
for table in ("users", "cats", "communities", "tasks", "feeding_logs", "impact_events"):
    try:
        counts[table] = connection.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
    except sqlite3.Error:
        counts[table] = "-"
print("✓ 数据库可以打开，integrity_check=ok，行数 %s" % counts)
PY
    [ $? -eq 0 ] || status=1
  else
    printf '✗ 缺 help-cat.db\n'; status=1
  fi

  if [ -f "$target/uploads.tar.gz" ]; then
    if tar -tzf "$target/uploads.tar.gz" >/dev/null 2>&1; then
      say "✓ 上传目录压缩包可解（$(tar -tzf "$target/uploads.tar.gz" | wc -l | tr -d ' ') 个条目）"
    else
      printf '✗ uploads.tar.gz 损坏\n'; status=1
    fi
  else
    say "· 没有 uploads.tar.gz（当时上传目录是空的）"
  fi
  return "$status"
}

if [ "$MODE" = "verify" ]; then
  if [ "$VERIFY_TARGET" = "latest" ]; then
    VERIFY_TARGET="$(find "$BACKUP_DIR" -maxdepth 1 -mindepth 1 -type d -name '20*' | sort | tail -1)"
    [ -n "$VERIFY_TARGET" ] || { echo "在 $BACKUP_DIR 里找不到备份目录" >&2; exit 1; }
  fi
  verify_backup "$VERIFY_TARGET"
  exit $?
fi

# ---- 备份 -----------------------------------------------------------------

STAMP="$(date +%Y%m%d-%H%M%S)"
TARGET="$BACKUP_DIR/$STAMP"

if [ "$DRY_RUN" -eq 1 ]; then
  cat <<EOF
会执行:
  1) 用 sqlite3 的在线备份 API 把 $DB_PATH 快照到 $TARGET/help-cat.db（WAL 下安全）
  2) 打包 $UPLOADS_DIR -> $TARGET/uploads.tar.gz
  3) 写 META.txt 与 SHA256SUMS，做一次 integrity_check
  4) 删除 $BACKUP_DIR 下超过 $KEEP_DAYS 天的备份
  5) 按配置上传到异地（$( [ -n "${HELPCAT_BACKUP_RCLONE_REMOTE:-}${HELPCAT_BACKUP_COSCMD_BUCKET:-}${HELPCAT_BACKUP_S3_URL:-}${HELPCAT_BACKUP_UPLOAD_CMD:-}" ] && echo 已配置 || echo '未配置' ))
EOF
  exit 0
fi

if [ ! -f "$DB_PATH" ]; then
  printf '数据库不存在：%s\n' "$DB_PATH" >&2
  exit 1
fi

mkdir -p "$TARGET" || exit 1

# 1) 一致性快照。直接 cp 一个有 WAL 的库会拿到坏副本。
"$PYTHON" - "$DB_PATH" "$TARGET/help-cat.db" <<'PY' || { echo "快照失败" >&2; exit 1; }
import sqlite3, sys
source = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
target = sqlite3.connect(sys.argv[2])
with target:
    source.backup(target)
integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
if integrity != "ok":
    raise SystemExit("integrity_check 失败: %s" % integrity)
# 快照会继承 WAL 模式，于是又生成 -wal/-shm 边文件；备份目录里不要它们，
# 否则校验和会在两次读取之间漂移。
target.execute("PRAGMA journal_mode=DELETE")
target.close(); source.close()
PY
rm -f "$TARGET/help-cat.db-wal" "$TARGET/help-cat.db-shm"

# 2) 上传目录
if [ -d "$UPLOADS_DIR" ] && [ -n "$(ls -A "$UPLOADS_DIR" 2>/dev/null)" ]; then
  tar -czf "$TARGET/uploads.tar.gz" -C "$(dirname "$UPLOADS_DIR")" "$(basename "$UPLOADS_DIR")" 2>/dev/null \
    || { echo "打包上传目录失败" >&2; exit 1; }
fi

# 3) 元数据 + 校验和
{
  printf '备份时间: %s\n' "$(date '+%F %T %z')"
  printf '数据库: %s (%s)\n' "$DB_PATH" "$(du -h "$TARGET/help-cat.db" | cut -f1)"
  printf '当前 release: %s\n' "$(readlink -f "$RELEASE_LINK" 2>/dev/null || echo '-')"
  printf 'H5 版本: %s\n' "$(sed -n 's/.*CURRENT_VERSION *= *"\([^"]*\)".*/\1/p' "$RELEASE_LINK/app/rescue/version.js" 2>/dev/null | head -1)"
  printf '主机: %s\n' "$(hostname)"
} > "$TARGET/META.txt"
( cd "$TARGET" && sha256sum $(ls | grep -v '^SHA256SUMS$') > SHA256SUMS 2>/dev/null || shasum -a 256 $(ls | grep -v '^SHA256SUMS$') > SHA256SUMS )

if ! verify_backup "$TARGET"; then
  printf '备份自检失败，保留现场：%s\n' "$TARGET" >&2
  exit 1
fi

# 4) 保留周期
PRUNED=0
while IFS= read -r old; do
  [ -n "$old" ] || continue
  rm -rf "$old" && PRUNED=$(( PRUNED + 1 ))
done < <(find "$BACKUP_DIR" -maxdepth 1 -mindepth 1 -type d -name '20*' -mtime "+$KEEP_DAYS")
say "· 清理超过 $KEEP_DAYS 天的备份：$PRUNED 个"

# 5) 异地
REMOTE_DONE=0
if [ -n "${HELPCAT_BACKUP_UPLOAD_CMD:-}" ]; then
  "$HELPCAT_BACKUP_UPLOAD_CMD" "$TARGET" && REMOTE_DONE=1
elif [ -n "${HELPCAT_BACKUP_RCLONE_REMOTE:-}" ] && command -v rclone >/dev/null 2>&1; then
  rclone copy "$TARGET" "$HELPCAT_BACKUP_RCLONE_REMOTE/$STAMP" && REMOTE_DONE=1
elif [ -n "${HELPCAT_BACKUP_COSCMD_BUCKET:-}" ] && command -v coscmd >/dev/null 2>&1; then
  coscmd upload -r "$TARGET" "/$STAMP" >/dev/null && REMOTE_DONE=1
elif [ -n "${HELPCAT_BACKUP_S3_URL:-}" ] && command -v aws >/dev/null 2>&1; then
  aws s3 cp --recursive "$TARGET" "$HELPCAT_BACKUP_S3_URL/$STAMP" --only-show-errors && REMOTE_DONE=1
fi

say "备份完成：$TARGET"
if [ "$REMOTE_DONE" -eq 1 ]; then
  say "· 已上传到异地"
else
  printf '⚠ 未配置异地目标（HELPCAT_BACKUP_RCLONE_REMOTE / COSCMD_BUCKET / S3_URL / UPLOAD_CMD），\n'
  printf '  这次只落到了本机 %s —— 磁盘故障仍会一起丢。详见 docs/wiki/部署回滚与运维.md。\n' "$BACKUP_DIR"
fi
exit 0

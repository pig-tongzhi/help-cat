#!/usr/bin/env bash
#
# 打包一次「可发布」的 help-cat 版本，并生成 SHA-256 清单。
#
# 只做两件事：把该发布的文件挑出来、算出校验和。备份、切换 symlink、
# nginx -t、重启 help-cat.service 都在服务器上按发布流程执行。
#
# 用法：
#   scripts/build_release.sh [输出目录]
#   默认输出到 work/releases/helpcat-<版本>-<时间戳>/（work/ 已被 gitignore）
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(sed -n 's/.*CURRENT_VERSION *= *"\([^"]*\)".*/\1/p' "$ROOT/app/rescue/version.js" | head -1)"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${1:-$ROOT/work/releases/helpcat-${VERSION:-unknown}-$STAMP}"

rm -rf "$OUT"
mkdir -p "$OUT"

# 静态资源。注意 welcome/ 是站点文档根（`/` 直接指向它），目录名不能改，
# 否则页内 styles.css / welcome.js 的相对路径会 404。
cp -R "$ROOT/app/rescue" "$OUT/rescue"
cp -R "$ROOT/app/welcome" "$OUT/welcome"
cp -R "$ROOT/admin" "$OUT/admin"

# 后端：server 包 + 迁移配置 + 依赖清单
mkdir -p "$OUT/backend"
cp -R "$ROOT/server" "$OUT/backend/server"
cp "$ROOT/alembic.ini" "$OUT/backend/alembic.ini"
[ -f "$ROOT/requirements-commercial.txt" ] && cp "$ROOT/requirements-commercial.txt" "$OUT/backend/"
[ -f "$ROOT/requirements.txt" ] && cp "$ROOT/requirements.txt" "$OUT/backend/"

# 本地缓存与数据库绝不进发布包
find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$OUT" \( -name '*.pyc' -o -name '*.sqlite3' \) -delete 2>/dev/null || true

{
  echo "version=${VERSION:-unknown}"
  echo "built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "git_commit=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
} > "$OUT/RELEASE"

# 校验和清单（相对路径 + 稳定排序，便于服务器端 shasum -c）
( cd "$OUT" && find . -type f ! -name SHA256SUMS | LC_ALL=C sort | xargs shasum -a 256 > SHA256SUMS )

echo "release:  $OUT"
echo "version:  ${VERSION:-unknown}"
echo "commit:   $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "files:    $(wc -l < "$OUT/SHA256SUMS" | tr -d ' ')"
echo "size:     $(du -sh "$OUT" | cut -f1)"
echo "manifest: $OUT/SHA256SUMS"

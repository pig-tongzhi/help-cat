#!/usr/bin/env bash
#
# 打包一次「可发布」的 help-cat 版本，并生成 SHA-256 清单。
#
# 只做两件事：把该发布的文件挑出来、算出校验和。备份、切换 symlink、
# nginx -t、重启 help-cat.service 都在服务器上按发布流程执行。
#
# 关键约定：**只从 git 跟踪的文件里挑**。这样产物完全确定 ——
# 既不会带上本地未跟踪文件（例如 server/__init__.py 这种只存在于开发机上的
# 空包标记），也不会夹带调试时留下的临时文件。换一台机器打包结果一致。
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

# 把 git 跟踪的 <repo 前缀> 复制到包内 <目标目录>：
# 前缀本身是文件时直接落在目标路径，是目录时保留其内部结构。
copy_tracked() {
  local prefix="$1" dest="$2" rel target
  while IFS= read -r -d '' rel; do
    if [ "$rel" = "$prefix" ]; then
      target="$OUT/$dest"
    else
      target="$OUT/$dest/${rel#"$prefix"/}"
    fi
    mkdir -p "$(dirname "$target")"
    cp "$ROOT/$rel" "$target"
  done < <(git -C "$ROOT" ls-files -z "$prefix")
}

# 静态资源。注意 welcome/ 是站点文档根（`/` 直接指向它），目录名不能改，
# 否则页内 styles.css / welcome.js 的相对路径会 404。
copy_tracked app/rescue rescue
copy_tracked app/welcome welcome
copy_tracked admin admin

# 后端：server 包 + 迁移配置 + 依赖清单
copy_tracked server backend/server
copy_tracked alembic.ini backend/alembic.ini
for extra in requirements-commercial.txt requirements.txt; do
  [ -f "$ROOT/$extra" ] && copy_tracked "$extra" "backend/$extra"
done

# 双保险：任何缓存/数据库/密钥文件都不进包
find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$OUT" \( -name '*.pyc' -o -name '*.sqlite3' -o -name '*.db' -o -name '.env' \) -delete 2>/dev/null || true

{
  echo "version=${VERSION:-unknown}"
  echo "built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "git_commit=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "tracked_only=1"
} > "$OUT/RELEASE"

# 校验和清单（相对路径 + 稳定排序，便于服务器端 shasum -c）
( cd "$OUT" && find . -type f ! -name SHA256SUMS | LC_ALL=C sort | xargs shasum -a 256 > SHA256SUMS )

echo "release:  $OUT"
echo "version:  ${VERSION:-unknown}"
echo "commit:   $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "files:    $(wc -l < "$OUT/SHA256SUMS" | tr -d ' ')"
echo "size:     $(du -sh "$OUT" | cut -f1)"
echo "manifest: $OUT/SHA256SUMS"

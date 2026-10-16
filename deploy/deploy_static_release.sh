#!/usr/bin/env bash
# help-cat · 静态发布（在云机器上以 root 执行）
#
#   bash deploy_static_release.sh <release 目录名> [nginx 新配置路径]
#
# 例：先在开发机 scripts/build_release.sh，然后
#   rsync -a --delete work/releases/helpcat-<版本>-<时间戳>/ \
#     root@175.178.41.19:/opt/help-cat/releases/<同名目录>/
#   scp deploy/nginx/helpcat.conf root@175.178.41.19:/tmp/helpcat.conf.new
#   ssh root@175.178.41.19 'bash /opt/help-cat/scripts/deploy_static_release.sh <同名目录> /tmp/helpcat.conf.new'
#
# 这份脚本是 2026-10-17 发布 r36 时实际跑通的流程固化，按
# docs/wiki/部署回滚与运维.md 的 7 条原则写成，几处实测坑记在下面：
#
#  * **release 是仓库结构**（`app/rescue`、`admin`、`server/`…），不是文档早期写的
#    `rescue/ admin/ backend/` —— 所以同步 IP 入口时源路径是 `app/rescue`。
#  * **两个入口必须分别更新**：`current` symlink（域名入口）+ IP 入口的独立副本。
#    只切 symlink，IP 入口还是旧版本（2026-09-23 踩过）。
#  * 验证域名入口要带 `--resolve` 走 443：它在 80 上是 301，且必须看 HTTPS 才拿到内容。
#  * 别在 `set -e` 下用 `v=$(curl … | grep …)` 当断言：抓不到就直接中止（r36 时撞过），
#    这里一律用显式判断 + `curl -m` 超时。
set -euo pipefail

REL_NAME="${1:?用法: deploy_static_release.sh <release 目录名> [nginx配置]}"
NGINX_NEW="${2:-}"
TS="$(date +%Y%m%d-%H%M%S)"
REL="/opt/help-cat/releases/$REL_NAME"
DIST="/data/purchase-system/frontend/dist/help-cat"
BK="/opt/help-cat/backups/${TS}-pre-${REL_NAME##*-}"
VERSION_TAG="$(cat "$REL/RELEASE" 2>/dev/null | sed -n 's/^version=//p' || true)"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()  { printf '  ✓ %s\n' "$*"; }
bad() { printf '  ✗ %s\n' "$*"; }

[ -d "$REL" ] || { bad "release 目录不存在: $REL"; exit 1; }

say "1/6 发布前备份"
mkdir -p "$BK/dist-help-cat"
cp -a "$DIST/." "$BK/dist-help-cat/" 2>/dev/null || true
readlink -f /opt/help-cat/current > "$BK/current-before.txt"
cp -a /etc/nginx/conf.d/helpcat.conf "$BK/helpcat.conf" 2>/dev/null || true
ok "备份到 $BK（回滚指向 $(cat "$BK/current-before.txt")）"

say "2/6 校验产物"
( cd "$REL" && [ -f SHA256SUMS ] && sha256sum -c SHA256SUMS >/tmp/hc-verify.log 2>&1 ) \
  || { bad "SHA256SUMS 校验失败"; tail -5 /tmp/hc-verify.log; exit 1; }
ok "SHA256SUMS 通过（$(wc -l < "$REL/SHA256SUMS" | tr -d ' ') 个文件）"

say "3/6 原子切换 symlink"
ln -sfn "$REL" /opt/help-cat/current.new
mv -T /opt/help-cat/current.new /opt/help-cat/current
ok "current → $(readlink -f /opt/help-cat/current)"

say "4/6 同步 IP 入口独立副本"
for pair in "app/rescue:rescue" "admin:admin"; do
  src="$REL/${pair%%:*}"; dst="$DIST/${pair##*:}"
  [ -d "$src" ] || { bad "release 里没有 ${pair%%:*}，跳过"; continue; }
  rm -rf "$dst.new"; cp -a "$src" "$dst.new"; rm -rf "$dst"; mv "$dst.new" "$dst"
  ok "同步 ${pair%%:*} → $dst"
done
chown -R root:root "$DIST"
find "$DIST" -type d -exec chmod 775 {} +
find "$DIST" -type f -exec chmod 664 {} +
ok "权限 775/664"

say "5/6 nginx 配置"
if [ -n "$NGINX_NEW" ] && [ -f "$NGINX_NEW" ]; then
  if diff -q /etc/nginx/conf.d/helpcat.conf "$NGINX_NEW" >/dev/null 2>&1; then
    ok "与线上一致，无需改动"
  else
    cp -a "$NGINX_NEW" /etc/nginx/conf.d/helpcat.conf
    if nginx -t >/tmp/hc-nginx.log 2>&1; then
      systemctl reload nginx; ok "已更新并 reload"
    else
      cp -a "$BK/helpcat.conf" /etc/nginx/conf.d/helpcat.conf
      bad "nginx -t 失败，已还原"; tail -3 /tmp/hc-nginx.log; exit 1
    fi
  fi
else
  ok "未提供新配置，跳过"
fi

say "6/6 双入口验证"
fail=0
# IP 入口：nginx 的静态副本（不跟随 symlink）
ip_ver="$(curl -s -m 8 -H 'Host: 175.178.41.19' http://127.0.0.1/help-cat/rescue/version.js | sed -n 's/.*CURRENT_VERSION *= *"\([^"]*\)".*/\1/p' | head -1)"
[ -n "$ip_ver" ] && ok "IP 入口版本: $ip_ver" || { bad "IP 入口拿不到版本"; fail=1; }
ip_lede="$(curl -s -m 8 -H 'Host: 175.178.41.19' http://127.0.0.1/help-cat/rescue/ | grep -o '杭州富阳的社区流浪猫投喂[^<]*' | head -1 || true)"
ok "IP 入口 lede: ${ip_lede:-（空）}"
# 域名入口：80 是 301，必须走 443 才能拿到内容
dom_ver="$(curl -sk -m 8 --resolve helpcat.xyz:443:127.0.0.1 https://helpcat.xyz/help-cat/rescue/version.js | sed -n 's/.*CURRENT_VERSION *= *"\([^"]*\)".*/\1/p' | head -1)"
[ -n "$dom_ver" ] && ok "域名入口版本: $dom_ver" || { bad "域名入口拿不到版本"; fail=1; }
[ -n "$VERSION_TAG" ] && { [ "$ip_ver" = "$VERSION_TAG" ] && [ "$dom_ver" = "$VERSION_TAG" ] \
  && ok "两个入口都等于 $VERSION_TAG" || { bad "版本不一致（期望 $VERSION_TAG）"; fail=1; }; }

say "结果"
if [ "$fail" = 0 ]; then
  echo "  ✓ 发布完成 $VERSION_TAG"
else
  echo "  ✗ 有验证未通过；回滚："
  echo "     ln -sfn $(cat "$BK/current-before.txt") /opt/help-cat/current"
  echo "     cp -a $BK/dist-help-cat/. $DIST/"
  exit 1
fi
echo "  回滚方法同一行命令（备份在 $BK）"

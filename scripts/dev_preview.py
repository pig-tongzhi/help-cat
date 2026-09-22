#!/usr/bin/env python3
"""本地预览服务器：静态页面 + API 反向代理。

生产环境由 nginx 提供静态文件，并把 `/help-cat-api` 转发给 FastAPI。这个脚本
在同一个端口上复刻同样的布局，所以欢迎页、H5 和后台都能在本地一次打开，前端
代码里的路径（`/help-cat-api`、`/help-cat/rescue/...`、`/admin/`）无需改动。

用法：
    python -m uvicorn server.helpcat.app:app --port 8000     # 另开一个终端
    python scripts/dev_preview.py --port 8199

    http://127.0.0.1:8199/           欢迎页（首页）
    http://127.0.0.1:8199/rescue/    现有 H5
    http://127.0.0.1:8199/admin/     后台（需要管理员令牌）
"""

import argparse
import http.server
import socketserver
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_PREFIX = "/help-cat-api"

# 顺序敏感：更具体的前缀放在前面，最后一条是兜底。
#
# 站点根目录就是欢迎页目录（`/` -> app/welcome/index.html）。这一点必须是“文档根”
# 而不是单纯把 `/` 重写到那个文件，否则页面同级的 styles.css / welcome.js 会因为
# 相对路径解析到站点根而 404 —— 这是部署时最容易踩的坑。
ROUTES = (
    ("/admin", ROOT / "admin"),
    ("/help-cat/rescue/assets", ROOT / "app" / "rescue" / "assets"),
    ("/help-cat/rescue", ROOT / "app" / "rescue"),
    ("/help-cat", ROOT / "app"),
    ("/welcome", ROOT / "app" / "welcome"),
    ("/rescue", ROOT / "app" / "rescue"),
    ("/assets", ROOT / "app" / "welcome" / "assets"),
    ("", ROOT / "app" / "welcome"),
)


class PreviewHandler(http.server.SimpleHTTPRequestHandler):
    api_origin = "http://127.0.0.1:8000"
    admin_token = ""

    extensions_map = dict(
        http.server.SimpleHTTPRequestHandler.extensions_map,
        **{
            ".webp": "image/webp",
            ".webmanifest": "application/manifest+json",
            ".mjs": "text/javascript",
            ".js": "text/javascript",
            ".css": "text/css",
        },
    )

    def log_message(self, fmt, *args):
        """保持输出干净；需要排查时改成 super() 调用即可。"""

    # ---- 路由 ----------------------------------------------------------
    def resolve(self, path):
        clean = path.split("?", 1)[0]
        for prefix, target in ROUTES:
            if clean == prefix or clean.startswith(prefix + "/"):
                rest = clean[len(prefix):].strip("/")
                return target / rest if rest else target
        return None

    def translate_path(self, path):
        resolved = self.resolve(path)
        # 交给 send_head 处理目录与 404。
        return str(resolved) if resolved is not None else str(ROOT / "__missing__")

    # ---- API 代理 ------------------------------------------------------
    def proxy(self, method):
        url = self.api_origin + self.path[len(API_PREFIX):]
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        request = urllib.request.Request(url, data=body, method=method)
        for header in ("Content-Type", "Authorization", "Idempotency-Key"):
            value = self.headers.get(header)
            if value:
                request.add_header(header, value)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload, status = response.read(), response.status
                content_type = response.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as error:
            payload, status = error.read(), error.code
            content_type = error.headers.get("Content-Type", "application/json")
        except (urllib.error.URLError, TimeoutError, OSError):
            payload = b'{"code":"preview_api_unreachable","message":"API \xe6\x9c\xaa\xe5\x90\xaf\xe5\x8a\xa8"}'
            status, content_type = 502, "application/json"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    # ---- 开发用登录跳板 -------------------------------------------------
    def dev_login(self):
        token = self.admin_token
        payload = (
            "<!doctype html><meta charset='utf-8'><title>dev login</title>"
            "<script>"
            "sessionStorage.setItem('help_cat_admin_token', %r);"
            "sessionStorage.setItem('help_cat_token', %r);"
            "location.replace('/admin/#messages');"
            "</script>"
        ) % (token, token)
        body = payload.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- 入口 ----------------------------------------------------------
    def do_GET(self):
        if self.path.startswith(API_PREFIX):
            return self.proxy("GET")
        if self.path.split("?", 1)[0] == "/__dev_login":
            return self.dev_login()
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith(API_PREFIX):
            return self.proxy("POST")
        self.send_error(405, "Method Not Allowed")

    # 注意：每个方法都必须各自转发真实的方法。曾经把 do_PATCH 直接指向 do_POST，
    # 而 do_POST 固定用 proxy("POST")，结果所有 PATCH 请求都被降级成 POST，
    # 后端返回 405，导致社区纠错、投喂点暂停/归档、补坐标等在本地「假失败」。
    def do_PATCH(self):
        if self.path.startswith(API_PREFIX):
            return self.proxy("PATCH")
        self.send_error(405, "Method Not Allowed")

    def do_PUT(self):
        if self.path.startswith(API_PREFIX):
            return self.proxy("PUT")
        self.send_error(405, "Method Not Allowed")

    def do_DELETE(self):
        if self.path.startswith(API_PREFIX):
            return self.proxy("DELETE")
        self.send_error(405, "Method Not Allowed")

    def do_OPTIONS(self):
        if self.path.startswith(API_PREFIX):
            return self.proxy("OPTIONS")
        self.send_error(405, "Method Not Allowed")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8199)
    parser.add_argument("--host", default="127.0.0.1",
                        help="监听地址。用 0.0.0.0 让同一局域网的手机也能打开；"
                             "注意 /__dev_login 会一并暴露给局域网")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="FastAPI 服务地址")
    parser.add_argument("--admin-token", default="", help="用于 /__dev_login 的管理员令牌（仅本地预览）")
    args = parser.parse_args()

    PreviewHandler.api_origin = args.api.rstrip("/")
    PreviewHandler.admin_token = args.admin_token
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((args.host, args.port), PreviewHandler) as server:
        print("本地预览: http://%s:%d/   (API -> %s)" % (args.host, args.port, PreviewHandler.api_origin), flush=True)
        if args.host not in ("127.0.0.1", "localhost"):
            print("提示: 已监听 %s，同一局域网的手机可访问；/__dev_login 也一并暴露。" % args.host, flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()

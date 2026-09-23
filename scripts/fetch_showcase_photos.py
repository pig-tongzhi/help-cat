#!/usr/bin/env python3
"""抓一批可自由使用的真实猫照，作为「演示档案」的占位照片。

为什么不「用 AI 生成图片」：这个环境里没有图像生成能力（没有接文生图 provider，
本机 ollama 只装了 embedding 模型），所以退一步用 **公有领域 / CC0** 的真实照片，
并把每一张的来源、作者、许可都记进 `scripts/showcase_photos/SOURCES.md`。

这个脚本只负责取素材：
  1. `--fetch N` 把候选下到 `work/showcase-fetch/`（已 gitignore）并写 manifest.json；
  2. 人（或 review）逐张看过，挑中的用 `--install` 转成 webp 落到
     `scripts/showcase_photos/`，同时生成 SOURCES.md。

用法：
    python scripts/fetch_showcase_photos.py --fetch 16
    python scripts/fetch_showcase_photos.py --install 00 03 05 ...

注意：这里用 Python 而不是 curl 抓 —— 这台机器的命令行 curl 访问 commons 报
"certificate has expired"，而 Python 的 ssl 走系统信任链，是好的。
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FETCH_DIR = ROOT / "work" / "showcase-fetch"
INSTALL_DIR = ROOT / "scripts" / "showcase_photos"

API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "help-cat-showcase/1.0 (https://github.com/pig-tongzhi/help-cat)"
# 只要没有署名义务的许可；CC BY / CC BY-SA 需要持续保留署名，能少一层义务就少一层。
ACCEPTED_LICENSES = ("CC0", "Public domain", "PD", "CC-PD-Mark")

SEARCHES = (
    "filetype:bitmap tabby cat portrait",
    "filetype:bitmap black cat",
    "filetype:bitmap white cat",
    "filetype:bitmap ginger cat",
    "filetype:bitmap calico cat",
    "filetype:bitmap grey cat",
    "filetype:bitmap kitten",
    "filetype:bitmap cat green eyes",
    "filetype:bitmap feral cat",
    "filetype:bitmap domestic cat sitting",
    "filetype:bitmap cat lying",
    "filetype:bitmap cat outdoors",
    "filetype:bitmap tuxedo cat",
    "filetype:bitmap tortoiseshell cat",
)

# 同一只猫的连拍（"Ginger cat on the street01..09"）会被当成九张不同的图，
# 做演示档案就变成满屏同一只猫。按去掉尾部数字的名字聚成一组，一组只留一张。
def series_key(title):
    stem = title[5:] if title.startswith("File:") else title
    stem = re.sub(r"\.(jpg|jpeg|png)$", "", stem, flags=re.IGNORECASE)
    return re.sub(r"[\s_-]*\d+$", "", stem).strip().lower()

MAX_WIDTH = 1100
WEBP_QUALITY = 82
# 站内猫卡是 4:5 竖版（`object-fit: cover`）。横图交给 CSS 裁会切掉两侧，
# 所以在这里就按 4:5 裁好，线上看到的就是裁完的效果，不会出现猫被切一半。
CARD_ASPECT = 4 / 5
# 居中裁会切到主体的那几张，单独给个水平焦点（0=最左，1=最右）。
# 14 号原图猫头偏右，居中裁正好从鼻子切过去。
CROP_FOCUS = {"14": 0.78}


def api_get(params):
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(API + "?" + query, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def plain_text(value):
    """extmetadata 里嵌着 HTML，只留纯文本。"""
    text = re.sub(r"<[^>]+>", "", value or "")
    return re.sub(r"\s+", " ", text).strip()


def search(term, limit=12):
    payload = api_get({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": term, "gsrnamespace": "6", "gsrlimit": str(limit),
        "prop": "imageinfo", "iiprop": "url|extmetadata|mime|size", "iiurlwidth": "1400",
    })
    pages = (payload.get("query") or {}).get("pages") or {}
    results = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") not in {"image/jpeg", "image/png"}:
            continue
        if (info.get("width") or 0) < 1000 or (info.get("height") or 0) < 800:
            continue
        metadata = info.get("extmetadata") or {}
        license_name = (metadata.get("LicenseShortName") or {}).get("value", "")
        if license_name not in ACCEPTED_LICENSES:
            continue
        results.append({
            "title": page["title"],
            "license": license_name,
            "author": plain_text((metadata.get("Artist") or {}).get("value", "")),
            "descriptionurl": info.get("descriptionurl", ""),
            "thumburl": info.get("thumburl") or info.get("url"),
            "width": info.get("width"), "height": info.get("height"),
            "search": term,
        })
    return results


def fetch(count):
    FETCH_DIR.mkdir(parents=True, exist_ok=True)
    seen, manifest = set(), []
    for term in SEARCHES:
        if len(manifest) >= count:
            break
        for item in search(term):
            key = series_key(item["title"])
            if key in seen or len(manifest) >= count:
                continue
            seen.add(key)
            slot = "%02d" % len(manifest)
            target = FETCH_DIR / (slot + ".jpg")
            payload = None
            for attempt in range(3):
                try:
                    request = urllib.request.Request(item["thumburl"], headers={"User-Agent": USER_AGENT})
                    with urllib.request.urlopen(request, timeout=90) as response:
                        payload = response.read()
                    break
                except Exception as exc:  # noqa: BLE001 - 网络抖动重试，仍失败才跳过
                    if attempt == 2:
                        print("  跳过 %s: %s" % (item["title"], exc))
            if payload is None:
                continue
            target.write_bytes(payload)
            item["slot"] = slot
            item["file"] = target.name
            item["bytes"] = target.stat().st_size
            manifest.append(item)
            print("%2s %-14s %5dKB  %s" % (slot, item["license"], item["bytes"] // 1024, item["title"][5:]))

    (FETCH_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n下载 %d 张到 %s" % (len(manifest), FETCH_DIR))
    print("逐张看过（read_image）之后，用 --install 把挑中的转成 webp 并写 SOURCES.md。")


def crop_to_card(image, focus=0.5):
    """居中裁成猫卡比例；已经比 4:5 更瘦的图不动。"""
    if image.width / image.height <= CARD_ASPECT:
        return image
    target_width = round(image.height * CARD_ASPECT)
    offset = round((image.width - target_width) * focus)
    offset = max(0, min(image.width - target_width, offset))
    return image.crop((offset, 0, offset + target_width, image.height))


def install(slots):
    from PIL import Image, ImageOps

    manifest = json.loads((FETCH_DIR / "manifest.json").read_text(encoding="utf-8"))
    by_slot = {item["slot"]: item for item in manifest}
    unknown = [slot for slot in slots if slot not in by_slot]
    if unknown:
        print("manifest 里没有这些序号：%s" % unknown, file=sys.stderr)
        return 2

    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for slot in slots:
        item = by_slot[slot]
        source = FETCH_DIR / item["file"]
        target = INSTALL_DIR / (slot + ".webp")
        with Image.open(source) as image:
            # 完整解码 + 重新编码：顺带丢掉原图的 EXIF/GPS，和站内上传走同一套标准。
            converted = ImageOps.exif_transpose(image).convert("RGB")
            converted = crop_to_card(converted, CROP_FOCUS.get(slot, 0.5))
            if converted.width > MAX_WIDTH:
                height = round(converted.height * MAX_WIDTH / converted.width)
                converted = converted.resize((MAX_WIDTH, height), Image.Resampling.LANCZOS)
            converted.save(target, format="WEBP", quality=WEBP_QUALITY, method=6)
        rows.append((slot, target.name, item, target.stat().st_size))
        print("%s -> %s (%dKB)" % (item["title"][5:40], target.name, target.stat().st_size // 1024))

    lines = [
        "# 演示猫照来源与许可",
        "",
        "这些是给「演示档案」用的占位照片，全部来自 Wikimedia Commons，许可是 **CC0 / 公有领域**",
        "（没有署名义务，也不限制商用）。它们**不是**救助站里真实的猫 —— 等有真实照片时，",
        "用 `python scripts/seed_showcase_cats.py --cleanup --execute` 把演示档案整体删掉，",
        "再按正常流程上传真实档案。",
        "",
        "重新生成这份清单与这些图片：",
        "",
        "```bash",
        "python scripts/fetch_showcase_photos.py --fetch 16",
        "python scripts/fetch_showcase_photos.py --install " + " ".join(slots),
        "```",
        "",
        "| 文件 | 原文件 | 许可 | 作者 | 来源 |",
        "|---|---|---|---|---|",
    ]
    for slot, name, item, size in rows:
        lines.append("| `%s` (%.0fKB) | %s | %s | %s | [Commons](%s) |" % (
            name, size / 1024, item["title"][5:], item["license"],
            item["author"] or "（未署名）", item["descriptionurl"]))
    lines.append("")
    (INSTALL_DIR / "SOURCES.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n写入 %s" % (INSTALL_DIR / "SOURCES.md"))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fetch", type=int, metavar="N", help="下载 N 张候选到 work/showcase-fetch/")
    parser.add_argument("--install", nargs="+", metavar="SLOT", help="把选中的序号转成 webp 并写 SOURCES.md")
    args = parser.parse_args()
    if args.fetch:
        fetch(args.fetch)
        return 0
    if args.install:
        return install(args.install)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

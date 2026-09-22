#!/usr/bin/env python3
"""重新生成桌面首屏的 77 素材（取景 + 底部淡出）。

为什么要这个脚本：主页面首屏的构图是踩过坑之后定下来的，参数不记下来就无法复现 ——
原素材 960x720、猫只占右侧 45%，放进只占半屏的视觉列后，中间出现大片死区，
右耳还被素材边界硬切一刀。改成近方形构图后才同时解决这两件事。

取景基线（由 tests/test_rescue_h5_contract.py 的三条断言守护）：
  * 近方形：宽高比 0.9~1.1，这样契约里既有的 `object-fit: contain` 能正好铺满视觉列
  * 猫头占画面 45%~80%（太小没有存在感，太大顶到边缘）
  * 头顶留白 > 20px、底部淡出 > 20px（身体不能被硬切在底边）
  * 外圈像素收敛到 --hero-backdrop #F5F1EB，且不能有近黑边像素

用法：
    scripts/render_hero_asset.py [原图] [输出]
默认从 work/asset-backup/hero-desktop.orig.webp（本地备份，已被 gitignore）读取，
写回 app/rescue/assets/77/hero-desktop.webp。跑完会自检上面四条约束。
"""
import sys
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = ROOT / "work" / "asset-backup" / "hero-desktop.orig.webp"
DEFAULT_OUT = ROOT / "app" / "rescue" / "assets" / "77" / "hero-desktop.webp"

BACKDROP = (245, 241, 235)   # --hero-backdrop
CROP_BOX = (200, 0, 960, 720)   # 左侧留暖色呼吸区，猫留在画面右侧
CANVAS = (760, 760)             # 近方形，头部约占 62%
FADE_FROM = 630                 # 下巴在 y≈430，淡出从 630 开始，绝不碰脸


def build(source: Path, target: Path) -> Image.Image:
    crop = Image.open(source).convert("RGB").crop(CROP_BOX)
    canvas = Image.new("RGB", CANVAS, BACKDROP)
    canvas.paste(crop, (0, 0))

    pixels = canvas.load()
    span = CANVAS[1] - 1 - FADE_FROM
    for y in range(FADE_FROM, CANVAS[1]):
        alpha = (y - FADE_FROM) / span
        alpha = alpha * alpha * (3 - 2 * alpha)      # smoothstep
        for x in range(CANVAS[0]):
            pixel = pixels[x, y]
            pixels[x, y] = tuple(
                round(channel + (backdrop - channel) * alpha)
                for channel, backdrop in zip(pixel, BACKDROP)
            )

    # 最外一圈直接置为暖色，保证边缘收敛
    for x in range(CANVAS[0]):
        pixels[x, 0] = BACKDROP
        pixels[x, CANVAS[1] - 1] = BACKDROP
    for y in range(CANVAS[1]):
        pixels[0, y] = BACKDROP
        pixels[CANVAS[0] - 1, y] = BACKDROP

    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, "WEBP", quality=82, method=6)
    return Image.open(target).convert("RGB")


def self_check(image: Image.Image) -> None:
    edges = []
    for x in range(image.width):
        edges += [image.getpixel((x, 0)), image.getpixel((x, image.height - 1))]
    for y in range(image.height):
        edges += [image.getpixel((0, y)), image.getpixel((image.width - 1, y))]

    near_black = sum(max(pixel) < 18 for pixel in edges)
    distances = sorted(sum(abs(c - b) for c, b in zip(pixel, BACKDROP)) for pixel in edges)
    warm_p85 = distances[int(len(distances) * .85)]
    seam_x = image.width // 2
    jumps = [
        sum(abs(a - b) for a, b in zip(image.getpixel((seam_x - 1, y)), image.getpixel((seam_x, y))))
        for y in range(image.height)
    ]
    diff = ImageChops.difference(image, Image.new("RGB", image.size, BACKDROP)).convert("L")
    box = diff.point(lambda value: 255 if value > 18 else 0).getbbox()

    ratio = image.width / image.height
    left, top, right, bottom = box
    share = (right - left) / image.width
    print("  size            %dx%d  ratio=%.2f" % (image.width, image.height, ratio))
    print("  near-black edge %d            (need 0)" % near_black)
    print("  warm edge p85   %d            (need < 42)" % warm_p85)
    print("  center seam     %.2f         (need < 8)" % (sum(jumps) / len(jumps)))
    print("  headroom top    %d px         (need > 20)" % top)
    print("  fade below      %d px         (need > 20)" % (image.height - bottom))
    print("  head share      %.0f%%         (need 45~80%%)" % (share * 100))

    assert near_black == 0
    assert warm_p85 < 42
    assert sum(jumps) / len(jumps) < 8
    assert 0.9 < ratio < 1.1
    assert 0.45 < share < 0.8
    assert top > 20 and image.height - bottom > 20


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    if not source.exists():
        raise SystemExit(
            "找不到原图 %s\n原素材备份在 work/asset-backup/ 下（已被 gitignore），"
            "或直接把原始照片路径作为第一个参数传入。" % source
        )
    print("source %s -> target %s" % (source, target))
    self_check(build(source, target))
    print("OK")


if __name__ == "__main__":
    main()

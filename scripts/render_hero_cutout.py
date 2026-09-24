#!/usr/bin/env python3
"""重新生成首屏用的 77 抠像素材（带 alpha）。

为什么要这个脚本：首屏现在的做法是"77 站在草坪里"，猫必须从背景里抠出来 ——
一张带米色背景的矩形照片贴在草地上会露出一整块矩形边界。抠像的参数（用哪个模型、
边缘怎么收、导出成什么格式）不记下来就无法复现，所以固化在这里。

契约基线（由 tests/test_rescue_h5_contract.py 的 test_hero_cat_is_a_cutout_with_no_rectangle 守护）：
  * 带 alpha 通道
  * 四条边基本透明（不透明像素占比 < 2%）—— 有一圈不透明就等于没抠干净
  * 头顶留白 > 12px（耳朵不能被画布切掉）、左右不贴边
  * 主体横向占比 > 45%
  * 脸中心完全不透明（半透明的猫看着像幽灵）

用法：
    scripts/render_hero_cutout.py [原图] [输出]
依赖 `rembg`（本机 venv 里装了；只在本地生成素材时用到，不进生产依赖）。

踩过的坑：
  1) 直接用 rembg 的原始输出会留一圈淡淡的灰白晕，浅色背景上看不出来，
     放到草地上很明显 —— 所以要把 alpha 收 1px（MinFilter）再把过渡带收窄。
  2) 有损 WebP 会压坏 alpha 边缘，导出用无损（约 193KB，仍远低于 450KB 上限）。
"""
import sys
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = ROOT / "app" / "rescue" / "assets" / "77" / "portrait.webp"
DEFAULT_OUT = ROOT / "app" / "rescue" / "assets" / "77" / "cat-cutout.webp"
TARGET_WIDTH = 760
ALPHA_FLOOR = 96     # 低于它直接归零（去掉那圈晕）
ALPHA_CEIL = 200     # 高于它直接完全不透明（保住脸和身体）


def build(source: Path, target: Path) -> Image.Image:
    from rembg import new_session, remove

    image = Image.open(source).convert("RGB")
    cut = remove(image, session=new_session("u2net"), alpha_matting=False).convert("RGBA")
    red, green, blue, alpha = cut.split()
    alpha = alpha.filter(ImageFilter.MinFilter(3))
    alpha = alpha.point(
        lambda value: 0 if value < ALPHA_FLOOR else (255 if value > ALPHA_CEIL else int((value - ALPHA_FLOOR) * 255 / (ALPHA_CEIL - ALPHA_FLOOR)))
    )
    cut = Image.merge("RGBA", (red, green, blue, alpha))
    cut = cut.resize((TARGET_WIDTH, round(cut.height * TARGET_WIDTH / cut.width)), Image.LANCZOS)
    cut.save(target, "WEBP", lossless=True, method=6)
    return cut


def verify(cut: Image.Image) -> None:
    alpha = cut.getchannel("A")
    width, height = cut.size
    ring = []
    for x in range(width):
        ring += [alpha.getpixel((x, 0)), alpha.getpixel((x, height - 1))]
    for y in range(height):
        ring += [alpha.getpixel((0, y)), alpha.getpixel((width - 1, y))]
    opaque = sum(1 for value in ring if value > 12) / len(ring)
    bbox = alpha.point(lambda value: 255 if value > 40 else 0).getbbox()
    assert opaque < 0.02, f"四边不透明像素占比 {opaque:.1%}，抠像没干净"
    assert bbox, "找不到主体"
    left, top, right, bottom = bbox
    assert top > 12, f"头顶留白只有 {top}px，耳朵会被切"
    assert left > 4 and width - right > 4, "主体贴住了左右边"
    assert (right - left) / width > 0.45, "主体太小"
    assert alpha.getpixel((width // 2, int(height * 0.42))) == 255, "脸中心不是完全不透明"
    print(f"✓ {cut.size} 四边不透明 {opaque:.2%} 主体占比 {(right - left) / width:.0%} 顶留白 {top}px")


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    cut = build(source, target)
    verify(cut)
    print(f"写出 {target} ({target.stat().st_size / 1024:.0f}KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

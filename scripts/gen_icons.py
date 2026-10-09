"""生成 Smart Agent PWA 图标（纯 Python 标准库，零依赖）。

输出到 server/static/icons/：
  icon-180.png / icon-192.png / icon-512.png   圆角渐变蓝底 + 白色闪电
  icon-maskable-512.png                         全幅蓝底，图形缩到 maskable 安全区内

用法：.venv/Scripts/python scripts/gen_icons.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "server" / "static" / "icons"

# 品牌渐变：顶部 #2563eb -> 底部 #1e40af
TOP = (37, 99, 235)
BOTTOM = (30, 64, 175)
WHITE = (255, 255, 255)

SUBSAMPLE = 4  # 4x4 超采样抗锯齿

# 闪电多边形（归一化坐标 0..1）
BOLT = (
    (0.58, 0.18), (0.34, 0.56), (0.48, 0.56), (0.42, 0.82),
    (0.68, 0.44), (0.52, 0.44), (0.62, 0.18),
)


def in_rounded_rect(x: float, y: float, size: float, radius: float) -> bool:
    """圆角矩形的有符号距离判定。"""
    hw = size / 2 - radius
    dx = max(abs(x - size / 2) - hw, 0.0)
    dy = max(abs(y - size / 2) - hw, 0.0)
    return dx * dx + dy * dy <= radius * radius


def in_polygon(px: float, py: float, poly: tuple) -> bool:
    """射线法点在多边形内判定。"""
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def gradient_color(y: float, size: float) -> tuple[int, int, int]:
    t = y / size
    return tuple(round(TOP[k] + (BOTTOM[k] - TOP[k]) * t) for k in range(3))


def _sample(x: float, y: float, size: float, bolt_poly: tuple, maskable: bool) -> tuple[int, int, int, int]:
    if not maskable and not in_rounded_rect(x, y, size, size * 0.19):
        return (0, 0, 0, 0)
    if in_polygon(x, y, bolt_poly):
        return (*WHITE, 255)
    return (*gradient_color(y, size), 255)


def render(size: int, maskable: bool = False) -> bytes:
    """渲染 size×size 的 RGBA 位图字节串。"""
    scale = 0.62 if maskable else 1.0  # maskable 安全区收缩
    # 归一化坐标 -> 像素坐标（含 maskable 收缩）
    bolt = tuple(
        (((x - 0.5) * scale + 0.5) * size, ((y - 0.5) * scale + 0.5) * size) for x, y in BOLT
    )
    rows = bytearray()
    for Y in range(size):
        row = bytearray([0])
        for X in range(size):
            r = g = b = a = 0
            n = 0
            for i in range(SUBSAMPLE):
                for j in range(SUBSAMPLE):
                    sx = X + (i + 0.5) / SUBSAMPLE
                    sy = Y + (j + 0.5) / SUBSAMPLE
                    pr, pg, pb, pa = _sample(sx, sy, size, bolt, maskable)
                    r += pr; g += pg; b += pb; a += pa
                    n += 1
            row += bytes((r // n, g // n, b // n, a // n))
        rows += row
    return bytes(rows)


def write_png(path: Path, size: int, rgba: bytes) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8bit RGBA
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", zlib.compress(rgba, 9)))
        f.write(chunk(b"IEND", b""))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jobs = [
        ("icon-180.png", 180, False),
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("icon-maskable-512.png", 512, True),
    ]
    for name, size, maskable in jobs:
        write_png(OUT_DIR / name, size, render(size, maskable))
        print(f"生成 {name} ({size}x{size})")


if __name__ == "__main__":
    main()

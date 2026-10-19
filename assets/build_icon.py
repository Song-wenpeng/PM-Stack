# -*- coding: utf-8 -*-
"""把候选 PNG 转成 Windows 多尺寸 ICO：python build_icon.py <input.png> <output.ico>"""
import sys

from PIL import Image, ImageDraw

src, dst = sys.argv[1], sys.argv[2]
img = Image.open(src).convert("RGBA")
w, h = img.size
mask = Image.new("L", (w, h), 0)
ImageDraw.Draw(mask).rounded_rectangle(
    [0, 0, w - 1, h - 1], radius=int(min(w, h) * 0.17), fill=255
)
img.putalpha(mask)
img.save(
    dst,
    format="ICO",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print("saved", dst)

"""Рисует иконку MTS Joiner: assets/icon.ico (16…256 px) и assets/icon.png.

Кинолента из трёх кадров, «сшитых» жёлтыми стежками, на сине-фиолетовом фоне — склейка видео.
Запуск: py -m pip install pillow && py tools/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"
S = 1024  # рисуем крупно, потом уменьшаем


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def draw(size_hint: int) -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # фон: скруглённый квадрат с диагональным градиентом
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    top, bottom = (54, 92, 255), (139, 56, 230)
    for y in range(S):
        gd.line([(0, y), (S, y)], fill=lerp(top, bottom, y / S) + (255,))
    mask = Image.new("L", (S, S), 0)
    margin = 40 if size_hint >= 48 else 0
    ImageDraw.Draw(mask).rounded_rectangle([margin, margin, S - margin, S - margin], radius=210, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)

    # плёнка
    small = size_hint <= 32
    x0, x1 = 120 if not small else 70, S - (120 if not small else 70)
    y0, y1 = 300, S - 300
    if small:
        y0, y1 = 270, S - 270
    d.rounded_rectangle([x0, y0, x1, y1], radius=40, fill=(245, 247, 255, 255))

    # перфорация
    if not small:
        hole_w, hole_h, gap = 54, 46, 34
        n = int((x1 - x0 - 60) // (hole_w + gap))
        start = x0 + ((x1 - x0) - (n * hole_w + (n - 1) * gap)) // 2
        for k in range(n):
            hx = start + k * (hole_w + gap)
            for hy in (y0 + 26, y1 - 26 - hole_h):
                d.rounded_rectangle([hx, hy, hx + hole_w, hy + hole_h], radius=10, fill=(40, 52, 120, 255))

    # три кадра
    fy0, fy1 = (y0 + 96, y1 - 96) if not small else (y0 + 60, y1 - 60)
    pad = 26 if not small else 40
    frames = 3
    fw = (x1 - x0 - pad * (frames + 1)) / frames
    colors = [((86, 170, 255), (40, 110, 230)), ((120, 150, 255), (70, 80, 220)), ((170, 120, 255), (110, 60, 210))]
    for k in range(frames):
        fx0 = x0 + pad + k * (fw + pad)
        fx1 = fx0 + fw
        c_top, c_bot = colors[k]
        for yy in range(int(fy0), int(fy1)):
            d.line([(fx0, yy), (fx1, yy)], fill=lerp(c_top, c_bot, (yy - fy0) / (fy1 - fy0)) + (255,))
        # «сцена» — светлый треугольник-play в среднем кадре
        if k == 1 and not small:
            cx, cy, r = (fx0 + fx1) / 2, (fy0 + fy1) / 2, (fy1 - fy0) * 0.28
            d.polygon([(cx - r * 0.7, cy - r), (cx - r * 0.7, cy + r), (cx + r, cy)], fill=(255, 255, 255, 235))

    # жёлтые стежки-швы между кадрами
    stitch = (255, 196, 40, 255)
    for k in range(1, frames):
        sx = x0 + k * (fw + pad) + pad / 2
        if small:
            d.rectangle([sx - 22, y0 - 40, sx + 22, y1 + 40], fill=stitch)
        else:
            d.rounded_rectangle([sx - 14, y0 - 70, sx + 14, y1 + 70], radius=14, fill=stitch)
            for yy in range(int(y0 - 30), int(y1 + 40), 90):
                d.rounded_rectangle([sx - 46, yy, sx + 46, yy + 22], radius=11, fill=stitch)
    return img


def main():
    OUT.mkdir(exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = []
    for sz in sizes:
        im = draw(sz).resize((sz, sz), Image.LANCZOS)
        imgs.append(im)
    big = draw(256).resize((256, 256), Image.LANCZOS)
    big.save(OUT / "icon.png")
    draw(256).resize((512, 512), Image.LANCZOS).save(ROOT / "docs" / "icon.png")
    imgs[-1].save(OUT / "icon.ico", format="ICO", sizes=[(s, s) for s in sizes], append_images=imgs[:-1])
    # превью всех размеров для проверки
    sheet = Image.new("RGBA", (sum(sizes) + 20 * len(sizes), 270), (255, 255, 255, 255))
    x = 10
    for im in imgs:
        sheet.paste(im, (x, 10), im)
        x += im.width + 20
    sheet.save(OUT / "preview.png")
    print("ok", OUT)


if __name__ == "__main__":
    main()

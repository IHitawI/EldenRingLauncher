"""Сглаженные примитивы для Tk-канваса.

Tk рисует овалы и скругления без сглаживания — на тёмном фоне это заметная
«лесенка». Здесь фигуры рисуются через PIL в 4× разрешении, уменьшаются с
LANCZOS и кэшируются как готовые PhotoImage.
"""
from collections import OrderedDict
from PIL import Image, ImageDraw, ImageFilter, ImageTk

SS = 4
_photos = OrderedDict()
_LIMIT = 400


def rgba(color, alpha=255):
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16), alpha


def _cached(key, build):
    photo = _photos.get(key)
    if photo is None:
        photo = ImageTk.PhotoImage(build())
        _photos[key] = photo
        if len(_photos) > _LIMIT:
            _photos.popitem(last=False)
    else:
        _photos.move_to_end(key)
    return photo


def _rounded_image(w, h, r, fill, outline, width, alpha):
    w, h = max(1, int(w)), max(1, int(h))
    big = Image.new("RGBA", (w*SS, h*SS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    draw.rounded_rectangle((0, 0, w*SS-1, h*SS-1), radius=int(r*SS),
                           fill=rgba(fill, alpha) if fill else None,
                           outline=rgba(outline) if outline else None, width=int(width*SS) if outline else 0)
    return big.resize((w, h), Image.Resampling.LANCZOS)


def rounded(w, h, r, fill, outline=None, width=1, alpha=255):
    """Скруглённый прямоугольник; alpha < 255 даёт полупрозрачную подложку."""
    key = ("rounded", int(w), int(h), r, fill, outline, width, alpha)
    return _cached(key, lambda: _rounded_image(w, h, min(r, h/2, w/2), fill, outline, width, alpha))


def pill(w, h, fill, outline=None, width=1, alpha=255):
    return rounded(w, h, h/2, fill, outline, width, alpha)


def circle(d, fill, outline=None, width=1, glow=None, glow_size=0):
    """Круг диаметром d; glow добавляет мягкое свечение вокруг (размер растёт на 2*glow_size)."""
    key = ("circle", d, fill, outline, width, glow, glow_size)

    def build():
        pad = glow_size
        size = int(d+pad*2)
        image = Image.new("RGBA", (size*SS, size*SS), (0, 0, 0, 0))
        if glow:
            halo = Image.new("RGBA", image.size, (0, 0, 0, 0))
            ImageDraw.Draw(halo).ellipse((pad*SS*0.5, pad*SS*0.5, (size-pad*0.5)*SS, (size-pad*0.5)*SS), fill=rgba(glow, 110))
            image.alpha_composite(halo.filter(ImageFilter.GaussianBlur(pad*SS*0.45)))
        draw = ImageDraw.Draw(image)
        draw.ellipse((pad*SS, pad*SS, (pad+d)*SS-1, (pad+d)*SS-1), fill=rgba(fill),
                     outline=rgba(outline) if outline else None, width=int(width*SS) if outline else 0)
        return image.resize((size, size), Image.Resampling.LANCZOS)
    return _cached(key, build)


def cover(path, size, letter, color, radius=10, outline="#4a4234"):
    """Обложка профиля: своя картинка со скруглёнными углами или градиентная
    плитка с первой буквой названия, если картинки нет."""
    from pathlib import Path
    mtime = 0
    if path:
        try:
            mtime = Path(path).stat().st_mtime
        except OSError:
            path = None
    key = ("cover", path, mtime, int(size), letter, color, radius, outline)

    def build():
        s = int(size)
        if path:
            from PIL import ImageOps
            with Image.open(path) as source:
                art = ImageOps.fit(source.convert("RGB"), (s, s), Image.Resampling.LANCZOS).convert("RGBA")
        else:
            top, bottom = rgba(color), (18, 16, 12, 255)
            art = Image.new("RGBA", (s, s))
            pixels = art.load()
            for y in range(s):
                t = y/max(1, s-1)
                row = tuple(int(top[i]+(bottom[i]-top[i])*t) for i in range(3))+(255,)
                for x in range(s):
                    pixels[x, y] = row
            try:
                from PIL import ImageFont
                from ui_media import assets_dir
                font = ImageFont.truetype(str(assets_dir()/"fonts"/"ElMessiri-Variable.ttf"), int(s*0.56))
                try:
                    font.set_variation_by_name("Bold")
                except Exception:
                    pass
                draw = ImageDraw.Draw(art)
                box = draw.textbbox((0, 0), letter, font=font)
                draw.text(((s-box[2]-box[0])/2, (s-box[3]-box[1])/2-box[1]*0.15), letter, font=font,
                          fill=(255, 226, 170, 235))
            except OSError:
                pass
        mask = Image.new("L", (s*SS, s*SS), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, s*SS-1, s*SS-1), radius=radius*SS, fill=255)
        art.putalpha(mask.resize((s, s), Image.Resampling.LANCZOS))
        frame = Image.new("RGBA", (s*SS, s*SS), (0, 0, 0, 0))
        ImageDraw.Draw(frame).rounded_rectangle((0, 0, s*SS-1, s*SS-1), radius=radius*SS, outline=rgba(outline), width=SS)
        art.alpha_composite(frame.resize((s, s), Image.Resampling.LANCZOS))
        return art
    return _cached(key, build)


def gradient(w, h, color, alpha_start, alpha_end, horizontal=True):
    """Линейный градиент прозрачности одного цвета — затемнение под текстом."""
    key = ("gradient", int(w), int(h), color, alpha_start, alpha_end, horizontal)

    def build():
        steps = int(w if horizontal else h) or 1
        line = Image.new("L", (steps, 1) if horizontal else (1, steps))
        for i in range(steps):
            t = i/max(1, steps-1)
            # smoothstep — без заметной «границы» у края градиента
            t = t*t*(3-2*t)
            value = int(alpha_start+(alpha_end-alpha_start)*t)
            line.putpixel((i, 0) if horizontal else (0, i), value)
        mask = line.resize((max(1, int(w)), max(1, int(h))))
        image = Image.new("RGBA", mask.size, rgba(color))
        image.putalpha(mask)
        return image
    return _cached(key, build)

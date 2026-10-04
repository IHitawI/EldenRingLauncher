"""Original asset loading and cancellable, background-only transitions."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tkinter as tk
from PIL import Image, ImageEnhance, ImageOps, ImageTk


def assets_dir():
    # Prefer shipped resources; do not confuse resources with writable user data.
    bundled = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"
    return bundled


class Assets:
    def __init__(self):
        self.root = assets_dir() / "figma"
        self.sources = {}
        self.cache = OrderedDict()

    def source(self, name):
        if name not in self.sources:
            with Image.open(self.root / name) as image:
                self.sources[name] = image.convert("RGBA")
        return self.sources[name]

    def photo(self, name, size, contain=True, mirror=False, tint=None):
        size = tuple(max(1, int(v)) for v in size)
        key = (name, size, contain, mirror, tint)
        if key not in self.cache:
            source = self.source(name)
            image = ImageOps.contain(source, size, Image.Resampling.LANCZOS) if contain else source.resize(size, Image.Resampling.LANCZOS)
            if mirror:
                image = ImageOps.mirror(image)
            if tint:
                # Одноцветный глиф: цвет из tint, прозрачность из исходника.
                colored = Image.new("RGBA", image.size, tint)
                colored.putalpha(image.getchannel("A"))
                image = colored
            self.cache[key] = ImageTk.PhotoImage(image)
            if len(self.cache) > 90:
                self.cache.popitem(last=False)
        self.cache.move_to_end(key)
        return self.cache[key]


class Background:
    """All Tk work stays on the UI thread; stale resize renders are discarded."""
    def __init__(self, app, scene):
        self.app, self.scene = app, scene
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="background")
        self.generation = 0
        self.current = None
        self.source = None
        self.closed = False
        self.poll_job = self.fade_job = None
        self.future = None

    @staticmethod
    def render(source, size, darkness):
        with Image.open(source) as image:
            image = ImageOps.fit(image.convert("RGB"), size, Image.Resampling.LANCZOS)
        return ImageEnhance.Brightness(image).enhance(1 - darkness / 100)

    def request(self, source, animated=True):
        if self.closed:
            return
        size = (max(1, self.scene.winfo_width()), max(1, self.scene.winfo_height()))
        if min(size) < 50:
            return
        self.generation += 1
        generation = self.generation
        self.source = Path(source)
        if self.future:
            self.future.cancel()
        for name in ("poll_job", "fade_job"):
            job = getattr(self, name)
            if job:
                self.app.after_cancel(job)
                setattr(self, name, None)
        darkness = max(0, min(90, int(self.app.data.get("settings", {}).get("background_darkness", 48))))
        future = self.executor.submit(self.render, source, size, darkness)
        self.future = future

        def poll():
            self.poll_job = None
            if self.closed or generation != self.generation:
                return
            if not future.done():
                self.poll_job = self.app.after(35, poll)
                return
            try:
                result = future.result()
            except (OSError, ValueError, MemoryError):
                return
            reduced = self.app.data.get("settings", {}).get("reduce_motion", False)
            # Пока идёт игра, памяти мало — никаких анимаций, просто готовый кадр.
            busy = getattr(self.app, "game_running", False)
            if (animated and not reduced and not busy and self.current and self.current.size == result.size
                    and self.app.state() not in ("iconic", "withdrawn")):
                previous = self.current
                steps = 8

                def fade(step=1):
                    if self.closed or generation != self.generation:
                        return
                    try:
                        frame = Image.blend(previous, result, step / steps)
                        self.scene.set_background(frame)
                        self.current = frame
                    except MemoryError:
                        # Не хватило памяти на кадр перехода — сразу ставим итоговый фон.
                        self.fade_job = None
                        self._show(result)
                        return
                    self.fade_job = self.app.after(70, fade, step + 1) if step < steps else None
                fade()
            else:
                self._show(result)
        poll()

    def _show(self, image):
        try:
            self.scene.set_background(image)
            self.current = image
        except MemoryError:
            pass  # оставляем предыдущий фон — лаунчер продолжает работать

    def close(self):
        self.closed = True
        self.generation += 1
        for job in (self.poll_job, self.fade_job):
            if job:
                self.app.after_cancel(job)
        self.executor.shutdown(wait=False, cancel_futures=True)

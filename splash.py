"""Стартовый экран из отдельных ассетов: обои, эмблема и живой текст."""
import math
import queue
import threading
import tkinter as tk
from PIL import Image, ImageOps, ImageEnhance, ImageTk
from ui_media import assets_dir
from ui_theme import load_embedded_font

from profiles import load
import app_info
import crash_log
import i18n
from i18n import tr

i18n.set_lang(load().get("settings", {}).get("lang", "ru"))


class StartupScreen:
    def __init__(self):
        self.root = tk.Tk()
        load_embedded_font(assets_dir())
        self.root.title(app_info.APP_NAME)
        try:
            self.root.iconbitmap(default=str(assets_dir() / "icon.ico"))
        except tk.TclError:
            pass
        self.root.overrideredirect(True)
        self.root.configure(bg="#090706")
        # Tk не позволяет совмещать fullscreen с безрамочным окном.
        # Растягиваем вручную: визуально это тот же полноэкранный старт.
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_width}x{screen_height}+0+0")
        self.canvas = tk.Canvas(self.root, bg="#090706", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.ready = queue.Queue(maxsize=1)
        self.launch_module = None
        self.requested = False
        self._draw()
        self.root.bind("<Button-1>", self._continue)
        self.root.bind("<Return>", self._continue)
        self.root.bind("<space>", self._continue)
        self.root.bind("<Escape>", lambda _event: self.root.destroy())
        self.root.focus_force()
        threading.Thread(target=self._warm_up, daemon=True).start()
        self.root.after(80, self._watch_ready)

    def _draw(self):
        width, height = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        backgrounds = sorted((assets_dir() / "default_backgrounds").glob("erdtree-01.*"))
        try:
            with Image.open(backgrounds[0]) as source:
                fitted = ImageOps.fit(source.convert("RGB"), (width, height), Image.Resampling.LANCZOS)
            self.background = ImageTk.PhotoImage(ImageEnhance.Brightness(fitted).enhance(0.4))
            self.canvas.create_image(width // 2, height // 2, image=self.background, anchor="center")
        except (tk.TclError, OSError, IndexError):
            self.canvas.create_rectangle(0, 0, width, height, fill="#18100b", outline="")
        # Эмблема и название рисуются отдельно, а не плоской картинкой.
        emblem = int(min(width, height) * 0.46)
        try:
            with Image.open(assets_dir() / "figma" / "branding" / "launcher-emblem.png") as source:
                logo = ImageOps.contain(source.convert("RGBA"), (emblem, emblem), Image.Resampling.LANCZOS)
            self.logo = ImageTk.PhotoImage(logo)
            self.canvas.create_image(width // 2, int(height * 0.38), image=self.logo, anchor="center")
        except (tk.TclError, OSError):
            pass
        title_y = int(height * 0.38) + emblem // 2 + 10
        self.canvas.create_text(width // 2, title_y, text="ELDEN RING", anchor="n",
                                fill="#ffdd99", font=("El Messiri", -max(34, emblem // 9), "bold"))
        self.canvas.create_text(width // 2, title_y + max(46, emblem // 7), text="L A U N C H E R", anchor="n",
                                fill="#b7a178", font=("El Messiri", -18, "bold"))
        self.prompt = self.canvas.create_text(
            width // 2, int(height * 0.86), text=tr("НАЖМИТЕ, ЧТОБЫ ПРОДОЛЖИТЬ"),
            fill="#f3cf77", font=("El Messiri", max(16, width // 60)),
        )
        self.hint = self.canvas.create_text(
            width // 2, int(height * 0.905), text=tr("ПОДГОТОВКА ЛАУНЧЕРА…"),
            fill="#b7a178", font=("El Messiri", 9, "bold"),
        )
        self.canvas.create_text(
            width // 2, height - 22, text=f"{tr(app_info.DISCLAIMER_SHORT)}   ·   v{app_info.VERSION}",
            fill="#8a7d63", font=("El Messiri", 9),
        )
        self._pulse()

    def _pulse(self, step=0):
        """Надпись «Нажмите…» мягко мерцает."""
        try:
            level = (math.sin(step / 12) + 1) / 2
            r, g, b = (int(150 + (243 - 150) * level), int(120 + (207 - 120) * level), int(70 + (119 - 70) * level))
            self.canvas.itemconfigure(self.prompt, fill=f"#{r:02x}{g:02x}{b:02x}")
            self.root.after(40, self._pulse, step + 1)
        except tk.TclError:
            pass

    def _warm_up(self):
        try:
            import main
            self.ready.put((main, None))
        except Exception as exc:
            self.ready.put((None, exc))

    def _watch_ready(self):
        try:
            module, error = self.ready.get_nowait()
            if error:
                if self.hint:
                    self.canvas.itemconfigure(self.hint, text=tr("ОШИБКА ЗАПУСКА"))
                self._error(error)
                return
            self.launch_module = module
            if self.hint:
                self.canvas.itemconfigure(self.hint, text=tr("ГОТОВО"))
            if self.requested:
                self._launch()
            return
        except queue.Empty:
            pass
        self.root.after(80, self._watch_ready)

    def _continue(self, _event=None):
        self.requested = True
        if self.launch_module:
            self._launch()

    def _launch(self):
        self.root.destroy()
        self.launch_module.run()

    def _error(self, error):
        crash_log.report(type(error), error, error.__traceback__)
        self.root.destroy()
        messagebox_root = tk.Tk()
        messagebox_root.withdraw()
        from tkinter import messagebox
        messagebox.showerror(app_info.APP_NAME, tr("Не удалось запустить лаунчер:\n{error}\n\nОтчёт сохранён: {path}").format(
            error=error, path=crash_log.log_path()))
        messagebox_root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if load().get("settings", {}).get("skip_startup_screen", False):
        import main
        main.run()
    else:
        StartupScreen().run()

"""Значок в системном трее (pystray). Если библиотеки нет — функция просто
недоступна, остальной лаунчер работает как обычно."""
import threading

try:
    import pystray
    from PIL import Image
except ImportError:  # сборка без pystray
    pystray = None


def available():
    return pystray is not None


class TrayIcon:
    """Колбэки pystray приходят из его потока — передаём их в Tk через after()."""

    def __init__(self, app, icon_path, title):
        self.app, self.icon_path, self.title = app, icon_path, title
        self.icon = None

    def _call(self, func):
        def handler(_icon=None, _item=None):
            try:
                self.app.after(0, func)
            except RuntimeError:
                pass
        return handler

    def show(self, menu_items):
        """menu_items: [(подпись, функция, по_умолчанию)]; повторный вызов обновляет меню."""
        if not available():
            return False
        self.hide()
        image = Image.open(self.icon_path).convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
        items = [pystray.MenuItem(label, self._call(func), default=default) for label, func, default in menu_items]
        self.icon = pystray.Icon("EldenRingLauncher", image, self.title, pystray.Menu(*items))
        threading.Thread(target=self.icon.run, daemon=True).start()
        return True

    def hide(self):
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None

    @property
    def visible(self):
        return self.icon is not None

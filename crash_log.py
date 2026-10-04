"""Журнал ошибок: любые необработанные исключения пишутся в data/launcher.log,
а пользователь видит понятное окно с предложением скопировать отчёт.

В оконном EXE нет консоли, поэтому без этого ошибка просто «молча» ломала бы
действие, и ни пользователь, ни автор не узнали бы причину.
"""
import sys
import threading
import time
import traceback
from datetime import datetime

import app_info
import profiles

MAX_SIZE = 512 * 1024
_last_dialog = 0.0


def log_path():
    return profiles.data_dir() / "launcher.log"


def write(text):
    path = log_path()
    try:
        if path.exists() and path.stat().st_size > MAX_SIZE:
            path.replace(path.with_suffix(".log.old"))
        with path.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {app_info.APP_NAME} {app_info.VERSION}\n{text.rstrip()}\n\n")
    except OSError:
        pass


def report(exc_type, exc, tb, root=None):
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    write(text)
    sys.__stderr__ and sys.__stderr__.write(text)
    _show_dialog(text, root)


def _show_dialog(text, root):
    """Не чаще раза в 5 секунд — чтобы цепочка ошибок не завалила окнами."""
    global _last_dialog
    if root is None or time.monotonic() - _last_dialog < 5:
        return
    _last_dialog = time.monotonic()
    try:
        from tkinter import messagebox
        from i18n import tr
        if messagebox.askyesno(
            tr("Что-то пошло не так"),
            tr("Произошла ошибка, но лаунчер продолжает работать.\n\nОтчёт сохранён:\n{path}\n\n"
               "Скопировать его, чтобы отправить автору в Discord ({discord})?").format(
                path=log_path(), discord=app_info.DISCORD),
            parent=root,
        ):
            root.clipboard_clear()
            root.clipboard_append(text)
    except Exception:
        pass


def install(root=None):
    sys.excepthook = lambda t, e, tb: report(t, e, tb, root)
    threading.excepthook = lambda args: report(args.exc_type, args.exc_value, args.exc_traceback,
                                                None)  # из потока окно не показываем
    if root is not None:
        root.report_callback_exception = lambda t, e, tb: report(t, e, tb, root)

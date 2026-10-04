"""Перевод интерфейса: исходные строки на русском, английские — в словаре EN.

tr("Текст {name}").format(name=...) — плейсхолдеры остаются одинаковыми в
обоих языках. Если перевода нет, показывается русская строка.
"""
LANG = "ru"


def set_lang(lang):
    global LANG
    LANG = lang if lang in ("ru", "en") else "ru"


def tr(text):
    if LANG == "en":
        return EN.get(text, text)
    return text


from i18n_en import EN  # noqa: E402  (словарь большой — в отдельном файле)

"""Перевод названий и подсказок из конфигов модов.

1. Ключи вида skip_splash_screens / enemyHealthScaling → «Skip splash screens».
2. Частые термины переводятся встроенным словарём (без сети).
3. Остальное — онлайн-переводчиком (Google Translate, запасной — MyMemory)
   в фоновом потоке; результат кэшируется в data/translations.json.
Переводится только текст настроек модов — никаких личных данных.
"""
import json
import re
import threading
import urllib.parse
import urllib.request

import profiles

_cache = None
_lock = threading.Lock()

GLOSSARY = {
    "enabled": "Включено", "enable": "Включить", "disabled": "Выключено", "disable": "Выключить",
    "fps": "FPS", "fps limit": "Ограничение FPS", "target fps": "Целевой FPS", "unlock fps": "Разблокировать FPS",
    "vsync": "Вертикальная синхронизация", "borderless": "Окно без рамки", "fullscreen": "Полноэкранный режим",
    "width": "Ширина", "height": "Высота", "resolution": "Разрешение", "scale": "Масштаб", "fov": "Поле зрения (FOV)",
    "volume": "Громкость", "language": "Язык", "password": "Пароль", "difficulty": "Сложность",
    "debug": "Отладка", "log": "Журнал", "logging": "Журналирование", "hotkey": "Горячая клавиша", "key": "Клавиша",
    "delay": "Задержка", "timeout": "Тайм-аут", "interval": "Интервал", "speed": "Скорость", "multiplier": "Множитель",
    "health": "Здоровье", "damage": "Урон", "stamina": "Выносливость", "poise": "Стойкость", "runes": "Руны",
    "camera": "Камера", "hud": "Интерфейс (HUD)", "ui": "Интерфейс", "brightness": "Яркость", "gamma": "Гамма",
    "skip intro": "Пропуск заставок", "skip logos": "Пропуск логотипов", "save file extension": "Расширение файла сохранения",
}


def _cache_file():
    return profiles.data_dir() / "translations.json"


def _load():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_cache_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _save():
    try:
        _cache_file().write_text(json.dumps(_cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def humanize(key: str) -> str:
    """skip_splash_screens / enemyHealthScaling / EnableFPS → «Skip splash screens»."""
    text = key.replace("_", " ").replace("-", " ").replace(".", " ")
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", text)
    words = text.split()
    if not words:
        return key
    keep_upper = {w for w in words if w.isupper() and len(w) <= 4}
    words = [w if w in keep_upper else w.lower() for w in words]
    words[0] = words[0][:1].upper() + words[0][1:]
    return " ".join(words)


def cached(text: str, lang: str = "ru") -> str | None:
    """Готовый перевод (словарь или кэш) без обращения к сети."""
    if not text or lang != "ru" or re.search(r"[А-Яа-яЁё]", text):
        return text
    low = text.strip().lower()
    if low in GLOSSARY:
        return GLOSSARY[low]
    with _lock:
        return _load().get(text)


def translate_async(texts, on_done, lang="ru"):
    """Переводит недостающие строки в фоне; on_done(dict) вызывается из потока."""
    missing = [t for t in dict.fromkeys(texts) if t and cached(t, lang) is None]
    if not missing or lang != "ru":
        return False

    def work():
        result = {}
        # пачками, разделяя строки переводом строки — так меньше запросов
        batch, size = [], 0
        for text in missing + [None]:
            if text is not None and size + len(text) < 1500:
                batch.append(text)
                size += len(text) + 1
                continue
            if batch:
                result.update(_translate_batch(batch))
            batch, size = ([text], len(text)) if text else ([], 0)
        if result:
            with _lock:
                _load().update(result)
                _save()
        on_done(result)
    threading.Thread(target=work, daemon=True).start()
    return True


def _translate_batch(batch):
    joined = "\n".join(batch)
    for engine in (_google, _mymemory):
        try:
            lines = engine(joined)
            if lines and len(lines) == len(batch):
                return {src: dst.strip() for src, dst in zip(batch, lines) if dst.strip()}
        except Exception:
            continue
    return {}


def _get(url, timeout=8):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 EldenRingLauncher"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _google(text):
    url = ("https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=ru&dt=t&q="
           + urllib.parse.quote(text))
    data = _get(url)
    translated = "".join(part[0] for part in data[0] if part and part[0])
    return translated.split("\n")


def _mymemory(text):
    url = "https://api.mymemory.translated.net/get?langpair=en|ru&q=" + urllib.parse.quote(text[:480])
    data = _get(url)
    return data["responseData"]["translatedText"].split("\n")

"""Распознавание модов и модпаков в распакованной папке.

Крупные моды поставляются по-разному:
- со своим Mod Engine 3 и готовым профилем .me3 (например, Reforged);
- со своим загрузчиком (Mod Engine 2 + .bat, например, Convergence);
- просто папкой с файлами игры (regulation.bin, chr, parts…) и/или DLL.
Лаунчер определяет тип сам, чтобы запускать мод так, как задумал автор.
"""
import os
from pathlib import Path

# Папки и файлы, которые лежат в корне пакета ассетов Elden Ring.
ASSET_DIRS = {"action", "asset", "chr", "cutscene", "event", "expression", "font", "map", "material", "menu",
              "movie", "msg", "other", "param", "parts", "script", "sd", "sfx", "shader", "sound"}
ASSET_FILES = {"regulation.bin"}
CONFIG_SUFFIXES = {".ini", ".toml", ".json", ".cfg", ".txt"}
SKIP_DIRS = {"__pycache__", ".git", "logs", "crash", "saves"}
MAX_DEPTH = 4


def _walk(root: Path, depth=0):
    """Обход папки с ограничением глубины и без служебных каталогов."""
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    for entry in entries:
        yield entry, depth
        if entry.is_dir() and depth < MAX_DEPTH and entry.name.lower() not in SKIP_DIRS:
            yield from _walk(entry, depth+1)


def is_package_root(folder: Path) -> bool:
    try:
        names = {p.name.lower() for p in folder.iterdir()}
    except OSError:
        return False
    return bool(names & ASSET_FILES) or len(names & ASSET_DIRS) >= 1 and any(
        (folder/name).is_dir() for name in names & ASSET_DIRS)


def find_package_roots(folder: Path) -> list[Path]:
    """Корни пакетов ассетов: сама папка или вложенные (мод часто упакован в подпапку)."""
    folder = Path(folder)
    if is_package_root(folder):
        return [folder]
    roots = []
    for entry, _depth in _walk(folder):
        if entry.is_dir() and is_package_root(entry):
            if not any(root in entry.parents for root in roots):
                roots.append(entry)
    return roots


def find_dlls(folder: Path, exclude_roots=()) -> list[Path]:
    """DLL-моды внутри папки (без загрузчиков вроде me3_mod_host.dll и modengine2.dll)."""
    loaders = {"me3_mod_host.dll", "modengine2.dll", "modengine2_launcher.dll", "dinput8.dll"}
    found = []
    for entry, _depth in _walk(Path(folder)):
        if entry.is_file() and entry.suffix.lower() == ".dll" and entry.name.lower() not in loaders:
            found.append(entry)
    return found


def config_files(paths) -> list[Path]:
    """Файлы настроек рядом с DLL-модами (тот же каталог и его подпапки до 1 уровня)."""
    seen, result = set(), []
    for path in paths:
        path = Path(path)
        folder = path if path.is_dir() else path.parent
        candidates = list(folder.glob("*")) + list(folder.glob("*/*"))
        for f in candidates:
            if f.is_file() and f.suffix.lower() in CONFIG_SUFFIXES and f.name.lower() not in {"readme.txt", "license.txt"}:
                key = str(f).lower()
                if key not in seen and (f.suffix.lower() != ".txt" or "config" in f.stem.lower() or "settings" in f.stem.lower()):
                    seen.add(key)
                    result.append(f)
    return result


def _squash(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def dll_configs(dll) -> list[Path]:
    """Собственные настройки DLL: ini/toml с тем же именем (erdyes.dll → erdyes.ini,
    ErdTools.dll → erd_tools.ini), рядом или в подпапке с именем мода."""
    dll = Path(dll)
    stem = _squash(dll.stem)
    result = []
    for folder in (dll.parent, dll.parent / dll.stem):
        if not folder.is_dir():
            continue
        for f in folder.iterdir():
            if f.is_file() and f.suffix.lower() in {".ini", ".toml", ".cfg", ".json"} and _squash(f.stem).startswith(stem):
                result.append(f)
    return sorted(result, key=lambda p: p.suffix.lower() != ".ini")


def pack_configs(folder) -> list[Path]:
    """ini/toml/cfg внутри модпака, без папок с ассетами (там тысячи служебных файлов)."""
    result = []
    for entry, _depth in _walk(Path(folder)):
        if not entry.is_file() or entry.suffix.lower() not in {".ini", ".toml", ".cfg"}:
            continue
        parts = {p.lower() for p in entry.relative_to(folder).parts[:-1]}
        if parts & ASSET_DIRS:
            continue
        result.append(entry)
    return sorted(result, key=lambda p: (p.suffix.lower() != ".ini", str(p).lower()))[:200]


def detect(folder) -> dict:
    """Тип модпака: "me3" (готовый профиль), "loader" (свой загрузчик/.bat) или "files"."""
    folder = Path(folder)
    me3_profiles, me3_exe, bats, me2_launcher, me2_config = [], None, [], None, None
    me3_profiles = find_me3_files(folder)
    for entry, depth in _walk(folder):
        name = entry.name.lower()
        if entry.is_file():
            if name == "me3.exe":
                # Модпаки кладут рядом сборки для Windows и для Linux/Proton — берём Windows.
                parts = {p.lower() for p in entry.parts}
                if me3_exe is None or ("linux" in {p.lower() for p in me3_exe.parts} and "linux" not in parts):
                    me3_exe = entry
            elif entry.suffix.lower() in (".bat", ".cmd") and depth <= 1:
                bats.append(entry)
            elif name == "modengine2_launcher.exe":
                me2_launcher = entry
            elif name.startswith("config_eldenring") and entry.suffix.lower() == ".toml":
                me2_config = entry
    info = {"folder": folder, "me3_profiles": me3_profiles, "me3_exe": me3_exe, "bats": sorted(bats),
            "me2_launcher": me2_launcher, "me2_config": me2_config}
    if me3_profiles:
        info["type"] = "me3"
    elif me2_launcher or _launch_bats(bats):
        info["type"] = "loader"
        info["launcher"] = (_launch_bats(bats) or [None])[0] or me2_launcher
    else:
        info["type"] = "files"
        info["packages"] = find_package_roots(folder)
        info["dlls"] = find_dlls(folder)
    return info


def find_me3_files(folder) -> list[Path]:
    """Профили .me3 на любой глубине, включая скрытые папки и файлы (os.walk их не пропускает)."""
    folder = Path(folder)
    found = []
    for root, _dirs, files in os.walk(folder, onerror=lambda _e: None):
        found += [Path(root) / name for name in files if name.lower().endswith(".me3")]
    return sorted(found, key=lambda p: (len(p.relative_to(folder).parts), str(p).lower()))


def _launch_bats(bats):
    """Батники запуска: Start_*.bat, launchmod_*.bat, Launch*.bat — в порядке предпочтения."""
    def score(path):
        n = path.stem.lower()
        if n.startswith("start"):
            return 0
        if n.startswith("launchmod"):
            return 1
        if "launch" in n or "play" in n:
            return 2
        return 9
    return [b for b in sorted(bats, key=score) if score(b) < 9]


def preferred_me3_profile(profiles, online=False):
    """Из нескольких .me3 выбираем подходящий: offline/online по режиму, иначе default."""
    def score(path):
        n = path.stem.lower()
        if ("online" in n) == online and ("offline" in n or "online" in n):
            return 0
        if "default" in n:
            return 1
        return 2
    return sorted(profiles, key=score)[0] if profiles else None

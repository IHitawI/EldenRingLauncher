import json
import os
import shutil
import sys
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


_user_dir = None


def user_dir() -> Path:
    """Куда писать пользовательские данные. Рядом с программой (портативный
    режим), а если там нельзя писать — например, лаунчер лежит в Program
    Files — в %APPDATA%\\EldenRingLauncher."""
    global _user_dir
    if _user_dir is None:
        base = app_dir()
        try:
            (base / "data").mkdir(exist_ok=True)
            probe = base / "data" / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            _user_dir = base
        except OSError:
            _user_dir = Path(os.environ.get("APPDATA", Path.home())) / "EldenRingLauncher"
            _user_dir.mkdir(parents=True, exist_ok=True)
    return _user_dir


def data_dir() -> Path:
    path = user_dir() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_file() -> Path:
    return data_dir() / "profiles.json"


def load() -> dict:
    try:
        with data_file().open(encoding="utf-8") as f:
            value = json.load(f)
        if not isinstance(value, dict) or "profiles" not in value:
            return {"profiles": []}
        value.setdefault("settings", {})
        value["settings"].setdefault("steam_background_enabled", True)
        value["settings"].setdefault("ui_opacity", 0.78)
        value["settings"].setdefault("background_darkness", 72)
        value["settings"].setdefault("background_interval_seconds", 15)
        value["settings"].setdefault("skip_startup_screen", False)
        value["settings"].setdefault("minimize_on_launch", False)
        value["settings"].setdefault("use_tray", True)
        value["settings"].setdefault("backup_saves", True)
        value["settings"].setdefault("backup_keep", 10)
        value.setdefault("downloads", {})
        value["settings"].setdefault("translate_configs", True)
        for profile in value["profiles"]:
            profile.setdefault("mods", [])
            profile.setdefault("start_online", False)
            profile.setdefault("savefile", "")
            for mod in profile["mods"]:
                mod.setdefault("kind", "package")
            _migrate_seamless_profile(profile)
        return value
    except (OSError, json.JSONDecodeError):
        return {"profiles": [], "settings": {}}


def save(data: dict) -> None:
    target = data_file()
    temp = target.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    temp.replace(target)


def add(data: dict, name: str, path: str, kind: str, launch_args: str = "") -> None:
    path = str(Path(path).resolve())
    data["profiles"] = [p for p in data["profiles"] if p["name"] != name]
    data["profiles"].append({"name": name, "path": path, "kind": kind, "launch_args": launch_args, "mods": []})
    save(data)


def exists(data: dict, name: str) -> bool:
    return any(p["name"] == name for p in data["profiles"])


def safe_folder_name(name: str) -> str:
    """Имя профиля → допустимое имя папки Windows."""
    cleaned = "".join("_" if char in '<>:"/\\|?*' or ord(char) < 32 else char for char in name)
    return cleaned.strip(" .") or "profile"


def remove(data: dict, name: str) -> None:
    data["profiles"] = [p for p in data["profiles"] if p["name"] != name]
    save(data)


def clone_vanilla(source: str, target: str) -> None:
    src, dst = Path(source), Path(target)
    if not (src / "eldenring.exe").is_file():
        raise ValueError("В исходной папке не найден eldenring.exe")
    if dst.exists() and any(dst.iterdir()):
        raise ValueError("Целевая папка уже существует и не пуста")
    shutil.copytree(src, dst, dirs_exist_ok=True)


def game_exe(path: str) -> Path:
    root = Path(path)
    direct = root / "eldenring.exe"
    nested = root / "Game" / "eldenring.exe"
    return direct if direct.is_file() else nested


STEAM_APP_ID = "1245620"
SEAMLESS_DLL = "ersc.dll"


def is_seamless(mod: dict) -> bool:
    return mod.get("role") == "seamless" or Path(mod.get("path", "")).name.lower() == SEAMLESS_DLL


def seamless_mod(profile: dict, enabled_only=False):
    """Seamless Co-op, подключённый к профилю (как DLL-мод), или None."""
    for mod in profile.get("mods", []):
        if is_seamless(mod) and (mod.get("enabled", True) or not enabled_only):
            return mod
    return None


def find_seamless_in_game(game_dir) -> Path | None:
    """ersc.dll, уже распакованный в папку игры (стандартная установка Seamless)."""
    game_dir = Path(game_dir)
    for candidate in (game_dir / "SeamlessCoop" / SEAMLESS_DLL, game_dir / SEAMLESS_DLL):
        if candidate.is_file():
            return candidate
    return None


def find_seamless_in_folder(folder) -> Path | None:
    """ersc.dll внутри распакованного архива Seamless Co-op."""
    folder = Path(folder)
    direct = find_seamless_in_game(folder)
    if direct:
        return direct
    for path in folder.rglob(SEAMLESS_DLL):
        return path
    return None


def add_seamless(data: dict, profile: dict, dll_path) -> dict:
    """Подключает Seamless Co-op к профилю: DLL первым в списке модов."""
    existing = seamless_mod(profile)
    if existing:
        existing.update({"path": str(Path(dll_path).resolve()), "enabled": True, "role": "seamless"})
    else:
        existing = {"name": "Seamless Co-op", "path": str(Path(dll_path).resolve()), "kind": "native",
                    "enabled": True, "role": "seamless"}
        profile.setdefault("mods", []).insert(0, existing)
    save(data)
    return existing


def seamless_settings_file(mod: dict) -> Path | None:
    folder = Path(mod["path"]).parent
    for name in ("ersc_settings.ini", "seamlesscoopsettings.ini"):
        if (folder / name).is_file():
            return folder / name
    return None


def _migrate_seamless_profile(profile: dict) -> None:
    """Старые отдельные Seamless-профили → обычный профиль с подключённым Seamless."""
    if profile.get("kind") != "seamless":
        return
    profile["kind"] = "vanilla"
    dll = find_seamless_in_game(game_exe(profile["path"]).parent)
    if dll and not seamless_mod(profile):
        profile["mods"].insert(0, {"name": "Seamless Co-op", "path": str(dll), "kind": "native",
                                   "enabled": True, "role": "seamless"})


def launch_mode(profile: dict) -> str:
    """Режим запуска профиля: "offline" (без EAC), "online" (EAC / серверы ME3)
    или "seamless" (свои серверы мода). Если режим не задан явно: установка
    из Steam-библиотеки — онлайн, копии и старые версии — офлайн."""
    if profile.get("kind") == "seamless" or seamless_mod(profile, enabled_only=True):
        return "seamless"
    if profile.get("kind") == "pack" and profile.get("pack_type") == "loader":
        return "pack"  # модпак со своим загрузчиком сам решает, как запускать игру
    mode = profile.get("launch_mode")
    if mode in ("online", "offline"):
        return mode
    if profile.get("kind") in ("mods", "pack"):
        return "online" if profile.get("start_online") else "offline"
    return "online" if "steamapps" in str(profile.get("path", "")).lower().replace("/", "\\").split("\\") else "offline"


def ensure_steam_appid(game_dir) -> None:
    """steam_appid.txt рядом с eldenring.exe: игра запускается прямо из этой
    папки, без перезапуска через Steam и без Easy Anti-Cheat (офлайн).
    Запуск из самого Steam при этом остаётся онлайн."""
    target = Path(game_dir) / "steam_appid.txt"
    try:
        if target.read_text(encoding="utf-8").strip() == STEAM_APP_ID:
            return
    except OSError:
        pass
    target.write_text(STEAM_APP_ID, encoding="utf-8")


_version_cache: dict = {}


def exe_version(path) -> str | None:
    """Версия файла eldenring.exe (FileVersion из ресурсов), например "2.6.1.0"."""
    exe = game_exe(path)
    try:
        stat = exe.stat()
    except OSError:
        return None
    key = (str(exe), stat.st_mtime, stat.st_size)
    if key in _version_cache:
        return _version_cache[key]
    version = None
    try:
        import ctypes
        from ctypes import wintypes
        size = ctypes.windll.version.GetFileVersionInfoSizeW(str(exe), None)
        if size:
            buffer = ctypes.create_string_buffer(size)
            if ctypes.windll.version.GetFileVersionInfoW(str(exe), 0, size, buffer):
                pointer, length = ctypes.c_void_p(), wintypes.UINT()
                if ctypes.windll.version.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
                    info = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32 * 13)).contents
                    ms, ls = info[2], info[3]  # dwFileVersionMS / dwFileVersionLS
                    version = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except (AttributeError, OSError):
        version = None
    _version_cache[key] = version
    return version


def version_label(profile: dict) -> str:
    """Подпись версии игры для карточки: известная версия из лаунчера или версия exe."""
    if profile.get("game_version"):
        return profile["game_version"]
    raw = exe_version(profile["path"])
    return f"exe {raw.removesuffix('.0')}" if raw else ""


def format_playtime(seconds: float, lang: str = "ru") -> str:
    minutes = int(seconds // 60)
    hours, minutes = divmod(minutes, 60)
    if lang == "en":
        return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"
    return f"{hours} ч {minutes:02d} мин" if hours else f"{minutes} мин"


def covers_dir() -> Path:
    path = data_dir() / "covers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def set_cover(data: dict, profile: dict, image_path: str) -> None:
    """Копирует картинку обложки в data/covers (уменьшенной до 512 px)."""
    from PIL import Image, ImageOps
    target = covers_dir() / f"{safe_folder_name(profile['name'])}.png"
    with Image.open(image_path) as image:
        image = ImageOps.fit(image.convert("RGB"), (512, 512), Image.Resampling.LANCZOS)
        image.save(target)
    profile["cover"] = str(target)
    save(data)


def add_mod(data: dict, profile_name: str, path: str, kind: str = "package") -> None:
    source = Path(path).resolve()
    if kind == "package" and not source.is_dir():
        raise ValueError("Папка мода не найдена")
    if kind == "native" and (not source.is_file() or source.suffix.lower() != ".dll"):
        raise ValueError("Выберите существующий DLL-файл мода")
    for profile in data["profiles"]:
        if profile["name"] == profile_name:
            mods = profile.setdefault("mods", [])
            if any(item["path"] == str(source) for item in mods):
                raise ValueError("Этот мод уже добавлен")
            mods.append({"name": source.name, "path": str(source), "kind": kind, "enabled": True})
            save(data)
            return


def toggle_mod(data: dict, profile_name: str, index: int) -> None:
    for profile in data["profiles"]:
        if profile["name"] == profile_name:
            item = profile.setdefault("mods", [])[index]
            item["enabled"] = not item.get("enabled", True)
            save(data)
            return


def remove_mod(data: dict, profile_name: str, index: int) -> None:
    for profile in data["profiles"]:
        if profile["name"] == profile_name:
            profile.setdefault("mods", []).pop(index)
            save(data)
            return


def move_mod(data: dict, profile_name: str, index: int, direction: int) -> None:
    for profile in data["profiles"]:
        if profile["name"] == profile_name:
            mods = profile.setdefault("mods", [])
            target = index + direction
            if 0 <= index < len(mods) and 0 <= target < len(mods):
                mods[index], mods[target] = mods[target], mods[index]
                save(data)
            return


def set_profile_option(data: dict, profile_name: str, key: str, value) -> None:
    for profile in data["profiles"]:
        if profile["name"] == profile_name:
            profile[key] = value
            save(data)
            return


def set_me3_path(data: dict, path: str) -> None:
    data.setdefault("settings", {})["me3_path"] = str(Path(path).resolve())
    save(data)


def find_me3(data: dict) -> Path | None:
    configured = data.get("settings", {}).get("me3_path", "")
    candidates = [Path(configured)] if configured else []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates += [
            Path(local) / "Programs" / "garyttierney" / "me3" / "bin" / "me3.exe",
            Path(local) / "garyttierney" / "me3" / "bin" / "me3.exe",
        ]
    found = shutil.which("me3") or shutil.which("me3.exe")
    if found:
        candidates.append(Path(found))
    return next((path for path in candidates if path.is_file()), None)


def steam_screenshot_paths() -> list[Path]:
    """Находит локальные Steam-скриншоты именно Elden Ring (AppID 1245620)."""
    roots: list[Path] = []
    if winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
            roots.append(Path(steam_path))
        except OSError:
            pass
    program_files = os.environ.get("ProgramFiles(x86)")
    if program_files:
        roots.append(Path(program_files) / "Steam")
    found: list[Path] = []
    for root in dict.fromkeys(roots):
        userdata = root / "userdata"
        if not userdata.is_dir():
            continue
        for folder in userdata.glob("*/760/remote/1245620/screenshots"):
            if folder.is_dir():
                found.extend(path for path in folder.iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png"})
    return sorted(set(found), key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)


def _toml_string(value: str) -> str:
    """Обычная TOML-строка в двойных кавычках (апострофы в путях не ломают файл)."""
    return '"' + value.replace("\\", "/").replace('"', '\\"') + '"'


def _me3_id(index: int, name: str) -> str:
    slug = "".join(char if char.isalnum() else "-" for char in name.lower()).strip("-")[:40] or "mod"
    return f"{index:02d}-{slug}"


COOP_WORDS = ("seamless", "coop", "co-op", "ersc")


def pack_me3_files(folder) -> list[Path]:
    """Готовые профили ME3 внутри модпака (корень и подпапки первого уровня)."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(set(folder.glob("*.me3")) | set(folder.glob("*/*.me3")))


def is_me3_pack(mod: dict) -> bool:
    """Мод — это целый модпак со своим профилем ME3 (например, Convergence)."""
    return mod.get("kind") == "pack" or (mod.get("kind") == "package" and bool(pack_me3_files(mod.get("path", ""))))


def choose_pack_profile(files, coop: bool, online: bool = False):
    """Выбор варианта профиля модпака: с Seamless или без, онлайн/офлайн, default."""
    def score(path):
        name = path.stem.lower()
        has_coop = any(word in name for word in COOP_WORDS)
        result = 0 if has_coop == coop else 10
        if ("online" in name) != online and ("online" in name or "offline" in name):
            result += 5
        if "default" in name:
            result -= 1
        return result
    return sorted(files, key=lambda p: (score(p), p.name))[0] if files else None


def expand_pack(folder, coop: bool, online: bool = False) -> dict:
    """Разворачивает модпак по его профилю ME3: DLL, пакеты и файл сохранения
    с абсолютными путями. Seamless из модпака не берётся — его ставит профиль."""
    import tomllib
    profile_file = choose_pack_profile(pack_me3_files(folder), coop, online)
    result = {"profile": profile_file, "natives": [], "packages": [], "savefile": None, "missing": []}
    if not profile_file:
        return result
    try:
        data = tomllib.loads(profile_file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return result
    base = profile_file.parent

    def resolve(entry):
        path = Path(entry.get("path", "")) if isinstance(entry, dict) else Path(str(entry))
        return path if path.is_absolute() else (base / path).resolve()

    for key in ("natives", "native"):
        for entry in data.get(key, []) or []:
            if isinstance(entry, dict) and entry.get("enabled") is False:
                continue
            path = resolve(entry)
            if path.name.lower() == SEAMLESS_DLL:
                continue
            (result["natives"] if path.is_file() else result["missing"]).append(path)
    for key in ("packages", "package"):
        for entry in data.get(key, []) or []:
            if isinstance(entry, dict) and entry.get("enabled") is False:
                continue
            path = resolve(entry)
            (result["packages"] if path.is_dir() else result["missing"]).append(path)
    result["savefile"] = data.get("savefile")
    return result


def _norm(path) -> str:
    try:
        return str(Path(path).resolve()).lower()
    except OSError:
        return str(path).lower()


def pack_parts(mod: dict, coop: bool, online: bool = False) -> list[dict]:
    """Части модпака по профилю автора: DLL и пакеты, с учётом выключенных
    пользователем. [{kind, path, enabled, exists}] в авторском порядке."""
    expanded = expand_pack(mod["path"], coop, online)
    disabled = {_norm(p) for p in mod.get("pack_disabled", [])}
    parts = [{"kind": "native", "path": str(p), "exists": True} for p in expanded["natives"]]
    parts += [{"kind": "package", "path": str(p), "exists": True} for p in expanded["packages"]]
    parts += [{"kind": "native" if p.suffix.lower() == ".dll" else "package", "path": str(p), "exists": False}
              for p in expanded["missing"]]
    for part in parts:
        part["enabled"] = _norm(part["path"]) not in disabled
    return parts


def toggle_pack_part(data: dict, mod: dict, path) -> None:
    """Включить/выключить отдельную DLL или пакет внутри модпака."""
    disabled = mod.setdefault("pack_disabled", [])
    key = _norm(path)
    kept = [p for p in disabled if _norm(p) != key]
    if len(kept) == len(disabled):
        kept.append(str(path))
    mod["pack_disabled"] = kept
    save(data)


def me3_entries(profile: dict) -> tuple[list, list, str | None]:
    """Итоговый порядок загрузки: Seamless первым, затем DLL и пакеты по списку
    (модпаки разворачиваются по своему профилю). Возвращает (natives, packages, savefile)."""
    natives, packages, savefile = [], [], profile.get("savefile") or None
    coop = seamless_mod(profile, enabled_only=True)
    if coop:
        natives.append(("Seamless Co-op", Path(coop["path"])))
    online = launch_mode(profile) == "online"
    for mod in profile.get("mods", []):
        if not mod.get("enabled", True) or is_seamless(mod):
            continue
        if is_me3_pack(mod):
            pack = expand_pack(mod["path"], bool(coop), online)
            off = {_norm(p) for p in mod.get("pack_disabled", [])}
            natives += [(f"{mod['name']}: {p.stem}", p) for p in pack["natives"] if _norm(p) not in off]
            packages += [(f"{mod['name']}: {p.name}", p) for p in pack["packages"] if _norm(p) not in off]
            savefile = savefile or pack["savefile"]
        elif mod.get("kind") == "native":
            natives.append((mod.get("name", "mod"), Path(mod["path"])))
        else:
            packages.append((mod.get("name", "mod"), Path(mod["path"])))
    return natives, packages, savefile


def write_me3_profile(data: dict, profile: dict) -> Path:
    """Создаёт стандартный TOML ModProfile, читаемый официальным ME3."""
    directory = data_dir() / "me3_profiles"
    directory.mkdir(parents=True, exist_ok=True)
    filename = "".join(char if char.isalnum() or char in "-_" else "_" for char in profile["name"]).strip("_") or "eldenring"
    target = directory / f"{filename}.me3"
    natives, packages, savefile = me3_entries(profile)
    lines = ['profileVersion = "v1"', ""]
    if savefile:
        lines += [f"savefile = {_toml_string(savefile)}", ""]
    online = launch_mode(profile) == "online"
    lines += [f"start_online = {'true' if online else 'false'}", "", "[[supports]]", 'game = "eldenring"', ""]
    # DLL: ME3 (с 0.8) грузит их строго в порядке профиля, а свои id для DLL не
    # учитывает (называет их по имени файла) — поэтому без id/load_after, иначе
    # запуск падает с «Required dependency is unavailable». Seamless — первый.
    for _name, path in natives:
        lines += ["[[natives]]", f"path = {_toml_string(str(path))}", ""]
    # Пакеты: порядок задаётся явно цепочкой load_after (id у пакетов ME3 учитывает).
    previous = None
    for index, (name, path) in enumerate(packages, start=1):
        mod_id = _me3_id(index, name)
        lines += ["[[packages]]", f'id = "{mod_id}"', f"path = {_toml_string(str(path))}"]
        if previous:
            lines.append(f'load_after = [{{ id = "{previous}", optional = false }}]')
        lines.append("")
        previous = mod_id
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def mod_conflicts(profile: dict) -> list[str]:
    """Файлы, которые есть сразу в нескольких пакетах (модпаки — по их профилю)."""
    owners: dict[str, list[str]] = {}
    _natives, packages, _savefile = me3_entries(profile)
    for name, root in packages:
        if not root.is_dir():
            continue
        for file in root.rglob("*"):
            if file.is_file():
                owners.setdefault(str(file.relative_to(root)).lower(), []).append(name)
    return [f"{path}: {', '.join(names)}" for path, names in owners.items() if len(names) > 1]

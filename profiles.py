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


def clone_check(source: str, target: str) -> str | None:
    """Почему копию нельзя создать (текст ошибки) или None."""
    src, dst = Path(source).resolve(), Path(target).resolve()
    if not (src / "eldenring.exe").is_file():
        return "В исходной папке не найден eldenring.exe"
    if dst == src or src in dst.parents:
        return "Копию нельзя создавать внутри папки самой игры. Выберите другую папку, например D:\\Games."
    if dst in src.parents:
        return "Нельзя копировать игру в папку, внутри которой она лежит. Выберите другую папку."
    if dst.exists() and any(dst.iterdir()):
        return "Целевая папка уже существует и не пуста"
    return None


def game_files(source: str) -> list[tuple[Path, int]]:
    """Все файлы папки игры с размерами (для подсчёта места и прогресса)."""
    files = []
    for path in Path(source).rglob("*"):
        try:
            if path.is_file():
                files.append((path, path.stat().st_size))
        except OSError:
            continue
    return files


def clone_vanilla(source: str, target: str, progress=None, files=None) -> None:
    """Копирует папку игры по файлам; progress(done_bytes, total_bytes, file)
    вызывается из этого же (фонового) потока."""
    error = clone_check(source, target)
    if error:
        raise ValueError(error)
    src, dst = Path(source), Path(target)
    files = files if files is not None else game_files(source)
    total = sum(size for _path, size in files) or 1
    done = 0
    dst.mkdir(parents=True, exist_ok=True)
    for path, size in files:
        out = dst / path.relative_to(src)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "rb") as reader, open(out, "wb") as writer:
            while chunk := reader.read(8 * 2**20):
                writer.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total, path.name)
        shutil.copystat(path, out, follow_symlinks=True)
    if progress:
        progress(total, total, "")


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


# DLL-обёртки, через которые сторонние загрузчики (Elden Mod Loader, старые
# Mod Engine 2, ReShade и т. п.) встраиваются в игру. Без EAC (офлайн, ME3)
# игра загружает их сама — старые моды могут ломать управление и камеру.
FOREIGN_DLLS = ("dinput8.dll", "winmm.dll", "dxgi.dll", "d3d11.dll", "d3d12.dll", "version.dll",
                "xinput1_3.dll", "xinput1_4.dll", "dsound.dll", "winhttp.dll")
DISABLED_SUFFIX = ".erl-off"


def foreign_loaders(game_dir) -> list[Path]:
    """Сторонние DLL-загрузчики в папке игры."""
    game_dir = Path(game_dir)
    try:
        return sorted(p for p in game_dir.iterdir() if p.is_file() and p.name.lower() in FOREIGN_DLLS)
    except OSError:
        return []


def foreign_loader_label(path) -> str:
    name = Path(path).name
    if name.lower() == "dinput8.dll" and (Path(path).parent / "mod_loader_config.ini").is_file():
        return f"{name} (Elden Mod Loader)"
    return name


def disable_loaders(game_dir) -> list[str]:
    """Временно переименовывает сторонние загрузчики; возвращает новые пути."""
    renamed = []
    for path in foreign_loaders(game_dir):
        target = path.with_name(path.name + DISABLED_SUFFIX)
        try:
            path.rename(target)  # если target уже есть, rename упадёт — чужие файлы не удаляем
            renamed.append(str(target))
        except OSError:
            continue
    return renamed


def restore_loaders(paths) -> list[str]:
    """Возвращает переименованные загрузчики; отдаёт те, что вернуть не вышло."""
    left = []
    for item in paths:
        path = Path(item)
        original = path.with_name(path.name[: -len(DISABLED_SUFFIX)]) if path.name.endswith(DISABLED_SUFFIX) else None
        if not original or not path.exists():
            continue
        try:
            if not original.exists():  # если пользователь уже положил новый файл — ничего не трогаем
                path.rename(original)
        except OSError:
            left.append(item)
    return left


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


_me3_cache: dict = {}


def pack_me3_files(folder, refresh=False) -> list[Path]:
    """Готовые профили ME3 внутри модпака (на любой глубине; результат кэшируется,
    потому что вызывается при каждой перерисовке списка модов)."""
    import modpacks
    key = _norm(folder)
    if refresh or key not in _me3_cache:
        _me3_cache[key] = modpacks.find_me3_files(folder) if Path(folder).is_dir() else []
    return [p for p in _me3_cache[key] if p.is_file()]


def pack_profile_file(mod: dict, coop: bool, online: bool = False):
    """Профиль ME3 модпака: выбранный пользователем или подобранный автоматически."""
    chosen = mod.get("me3_file")
    if chosen and Path(chosen).is_file():
        return Path(chosen)
    return choose_pack_profile(pack_me3_files(mod.get("path", "")), coop, online)


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


def expand_pack(folder, coop: bool, online: bool = False, profile_file=None) -> dict:
    """Разворачивает модпак по его профилю ME3: DLL, пакеты и файл сохранения
    с абсолютными путями. Seamless из модпака не берётся — его ставит профиль."""
    import tomllib
    profile_file = profile_file or choose_pack_profile(pack_me3_files(folder), coop, online)
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
    expanded = expand_pack(mod["path"], coop, online, pack_profile_file(mod, coop, online))
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
            pack = expand_pack(mod["path"], bool(coop), online, pack_profile_file(mod, bool(coop), online))
            off = {_norm(p) for p in mod.get("pack_disabled", [])}
            natives += [(f"{mod['name']}: {p.stem}", p) for p in pack["natives"] if _norm(p) not in off]
            packages += [(f"{mod['name']}: {p.name}", p) for p in pack["packages"] if _norm(p) not in off]
            savefile = savefile or pack["savefile"]
        elif mod.get("kind") == "native":
            natives.append((mod.get("name", "mod"), Path(mod["path"])))
        else:
            packages.append((mod.get("name", "mod"), Path(mod["path"])))
    return natives, packages, savefile


def _me3_filename(profile: dict) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in profile["name"]).strip("_") or "eldenring"


def custom_me3(profile: dict) -> Path | None:
    """Свой файл .me3 профиля (ручной режим): лаунчер запускает его как есть."""
    path = profile.get("me3_custom")
    return Path(path) if path and Path(path).is_file() else None


def custom_me3_dir() -> Path:
    return data_dir() / "me3_profiles" / "custom"


def is_own_custom(path) -> bool:
    """Файл создан лаунчером (лежит в data/me3_profiles/custom) — его можно удалять."""
    try:
        return custom_me3_dir().resolve() in Path(path).resolve().parents
    except OSError:
        return False


def create_custom_me3(data: dict, profile: dict) -> Path:
    """Новый свой .me3: начинается с того, что лаунчер собрал бы сам."""
    directory = custom_me3_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{_me3_filename(profile)}.me3"
    number = 2
    while target.exists():
        target = directory / f"{_me3_filename(profile)} ({number}).me3"
        number += 1
    target.write_text(render_me3(profile), encoding="utf-8")
    profile["me3_custom"] = str(target)
    save(data)
    return target


def check_me3_text(text: str) -> str | None:
    """Ошибка в тексте профиля ME3 (TOML) или None."""
    import tomllib
    try:
        parsed = tomllib.loads(text)
    except ValueError as exc:
        return f"TOML: {exc}"
    if "profileVersion" not in parsed:
        return "Нет строки profileVersion = \"v1\""
    for key in ("natives", "native", "packages", "package"):
        for entry in parsed.get(key, []) or []:
            if not isinstance(entry, dict) or not entry.get("path"):
                return "В разделах [[natives]] и [[packages]] у каждой записи должен быть path"
    return None


def seamless_block(dll) -> str:
    return f"[[natives]]\npath = {_toml_string(str(dll))}\nload_early = true\n"


def add_seamless_to_me3(path, dll) -> bool:
    """Вписывает Seamless первым в [[natives]] своего .me3 (с load_early = true).
    False — уже есть или файл не прочитать."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return False
    if SEAMLESS_DLL in text.lower():
        return False
    block = seamless_block(dll)
    marker = text.find("[[natives]]")
    if marker < 0:
        marker = text.find("[[native]]")
    text = text[:marker] + block + "\n" + text[marker:] if marker >= 0 else text.rstrip() + "\n\n" + block
    Path(path).write_text(text, encoding="utf-8")
    return True


def seamless_without_early(text: str) -> bool:
    """В тексте .me3 есть Seamless, но без load_early = true."""
    import tomllib
    try:
        parsed = tomllib.loads(text)
    except ValueError:
        return False
    for key in ("natives", "native"):
        for entry in parsed.get(key, []) or []:
            if isinstance(entry, dict) and str(entry.get("path", "")).replace("\\", "/").lower().endswith(SEAMLESS_DLL):
                return entry.get("load_early") is not True
    return False


def me3_file_savefile(path) -> str | None:
    import tomllib
    try:
        return tomllib.loads(Path(path).read_text(encoding="utf-8-sig")).get("savefile")
    except (OSError, ValueError):
        return None


def profile_savefile(profile: dict) -> str | None:
    """Имя файла сохранения, которое использует профиль (None — обычный ER0000.sl2)."""
    custom = custom_me3(profile)
    if custom:
        return me3_file_savefile(custom)
    if not any(m.get("enabled", True) for m in profile.get("mods", [])) and not profile.get("savefile"):
        return None
    return me3_entries(profile)[2]


def write_me3_profile(data: dict, profile: dict) -> Path:
    """Файл профиля для запуска ME3: свой (ручной режим) или собранный лаунчером."""
    custom = custom_me3(profile)
    if custom:
        return custom
    directory = data_dir() / "me3_profiles"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{_me3_filename(profile)}.me3"
    target.write_text(render_me3(profile), encoding="utf-8")
    return target


def render_me3(profile: dict) -> str:
    """Стандартный TOML ModProfile, читаемый официальным ME3."""
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
        lines += ["[[natives]]", f"path = {_toml_string(str(path))}"]
        if Path(path).name.lower() == SEAMLESS_DLL:
            lines.append("load_early = true")  # Seamless должен загрузиться раньше всех остальных DLL
        lines.append("")
    # Пакеты: порядок задаётся явно цепочкой load_after (id у пакетов ME3 учитывает).
    previous = None
    for index, (name, path) in enumerate(packages, start=1):
        mod_id = _me3_id(index, name)
        lines += ["[[packages]]", f'id = "{mod_id}"', f"path = {_toml_string(str(path))}"]
        if previous:
            lines.append(f'load_after = [{{ id = "{previous}", optional = false }}]')
        lines.append("")
        previous = mod_id
    return "\n".join(lines)


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

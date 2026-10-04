"""Безопасные локальные проверки Steam перед загрузкой."""

import os
import re
import subprocess
from pathlib import Path

APP_ID = "1245620"
ERDTREE_APP_ID = "2778580"
TARNISHED_PACK_APP_ID = "3655690"


def steam_running() -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"],
            capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "steam.exe" in result.stdout.lower()
    except OSError:
        return False


def _steam_roots() -> list[Path]:
    roots = [Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Steam"]
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            roots.insert(0, Path(winreg.QueryValueEx(key, "SteamPath")[0]))
    except (ImportError, OSError):
        pass
    # Многие пользователи ставят Steam на D:/E:, а путь в реестре может быть
    # недоступен при проверке из другого контекста Windows.
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        for suffix in ("Steam", "SteamLibrary", "Games/Steam"):
            candidate = Path(f"{letter}:/{suffix}")
            if candidate.is_dir():
                roots.append(candidate)
    return list(dict.fromkeys(root for root in roots if root.is_dir()))


def _libraries(root: Path) -> list[Path]:
    libraries = [root]
    file = root / "steamapps" / "libraryfolders.vdf"
    if file.is_file():
        try:
            for raw in re.findall(r'"path"\s+"([^"]+)"', file.read_text(encoding="utf-8", errors="ignore")):
                candidate = Path(raw.replace("\\\\", "\\"))
                if candidate.is_dir():
                    libraries.append(candidate)
        except OSError:
            pass
    return libraries


def installed_apps() -> set[str]:
    apps: set[str] = set()
    for root in _steam_roots():
        for library in _libraries(root):
            steamapps = library / "steamapps"
            for app_id in (APP_ID, ERDTREE_APP_ID, TARNISHED_PACK_APP_ID):
                if (steamapps / f"appmanifest_{app_id}.acf").is_file():
                    apps.add(app_id)
    return apps


def find_game_dirs() -> list[Path]:
    """Папки Game с eldenring.exe во всех найденных Steam-библиотеках."""
    found: list[Path] = []
    for root in _steam_roots():
        for library in _libraries(root):
            game = library / "steamapps" / "common" / "ELDEN RING" / "Game"
            if (game / "eldenring.exe").is_file():
                found.append(game.resolve())
    return list(dict.fromkeys(found))


def _base_manifests() -> list[Path]:
    manifests: list[Path] = []
    for root in _steam_roots():
        for library in _libraries(root):
            manifest = library / "steamapps" / f"appmanifest_{APP_ID}.acf"
            if manifest.is_file():
                manifests.append(manifest)
    return manifests


def _manifest_has(manifests: list[Path], app_id: str) -> bool:
    for manifest in manifests:
        try:
            if app_id in manifest.read_text(encoding="utf-8", errors="ignore"):
                return True
        except OSError:
            continue
    return False


def status(game_paths: list[str] | None = None) -> dict[str, str | bool]:
    installed = installed_apps()
    manifests = _base_manifests()
    game_dirs = [Path(path) for path in (game_paths or [])]
    base_files = any((folder / "eldenring.exe").is_file() for folder in game_dirs)
    # Shadow of the Erdtree действительно поставляется файлами DLC.bdt/DLC.bhd.
    shadow_files = any((folder / "DLC.bdt").is_file() for folder in game_dirs)
    return {
        "steam_running": steam_running(),
        "base_installed": APP_ID in installed or bool(manifests) or base_files,
        "erdtree_installed": ERDTREE_APP_ID in installed or _manifest_has(manifests, ERDTREE_APP_ID) or shadow_files,
        # Tarnished Pack может быть entitlement без отдельного depot-файла;
        # поэтому ищем как отдельный манифест, так и запись в манифесте игры.
        "tarnished_installed": TARNISHED_PACK_APP_ID in installed or _manifest_has(manifests, TARNISHED_PACK_APP_ID),
        # Владелец DLC определяется сервером Steam при SteamCMD login/download.
        "license_note": "Лицензия подтверждается SteamCMD при входе.",
    }

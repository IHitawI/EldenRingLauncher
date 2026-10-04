"""Резервные копии сохранений Elden Ring.

Сохранения лежат в %APPDATA%\\EldenRing\\<SteamID64>\\ (ER0000.sl2 — ваниль,
ER0000.co2 — Seamless Co-op, плюс .bak и файлы ME3-профилей). Копии хранятся
в data/save_backups/<дата-время>/<SteamID64>/ вместе с meta.json.
"""
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import profiles

SAVE_SUFFIXES = {".sl2", ".co2", ".bak", ".vdf", ".mod", ".sl2mod"}


def saves_root() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / "EldenRing"


def save_dirs() -> list[Path]:
    root = saves_root()
    if not root.is_dir():
        return []
    return [d for d in root.iterdir() if d.is_dir() and d.name.isdigit() and _save_files(d)]


def _save_files(folder: Path) -> list[Path]:
    return [f for f in folder.iterdir() if f.is_file() and (f.suffix.lower() in SAVE_SUFFIXES or f.name.upper().startswith("ER0000"))]


def backups_root() -> Path:
    path = profiles.data_dir() / "save_backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def game_running() -> bool:
    try:
        result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq eldenring.exe", "/NH"], capture_output=True, text=True,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return "eldenring.exe" in result.stdout.lower()
    except OSError:
        return False


def backup(reason: str, profile: str = "", auto: bool = False) -> Path | None:
    """Копирует все сохранения; None, если копировать нечего."""
    dirs = save_dirs()
    if not dirs:
        return None
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    target = backups_root() / stamp
    suffix = 1
    while target.exists():
        target = backups_root() / f"{stamp}_{suffix}"
        suffix += 1
    total, count = 0, 0
    for folder in dirs:
        dest = target / folder.name
        dest.mkdir(parents=True, exist_ok=True)
        for file in _save_files(folder):
            shutil.copy2(file, dest / file.name)
            total += file.stat().st_size
            count += 1
    meta = {"created": datetime.now().isoformat(timespec="seconds"), "reason": reason, "profile": profile,
            "auto": auto, "files": count, "size": total}
    (target / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def list_backups() -> list[dict]:
    items = []
    for folder in backups_root().iterdir():
        meta_file = folder / "meta.json"
        if not folder.is_dir() or not meta_file.is_file():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        meta["path"] = folder
        items.append(meta)
    return sorted(items, key=lambda m: m.get("created", ""), reverse=True)


def restore(folder: Path) -> Path | None:
    """Перед восстановлением сохраняет текущее состояние — его тоже можно вернуть."""
    safety = backup("Перед восстановлением", auto=False)
    root = saves_root()
    for steam_dir in folder.iterdir():
        if not steam_dir.is_dir():
            continue
        dest = root / steam_dir.name
        dest.mkdir(parents=True, exist_ok=True)
        for file in steam_dir.iterdir():
            if file.is_file():
                shutil.copy2(file, dest / file.name)
    return safety


def delete(folder: Path) -> None:
    folder = Path(folder).resolve()
    if backups_root().resolve() in folder.parents:
        shutil.rmtree(folder, ignore_errors=True)


def prune(keep: int) -> None:
    """Оставляет только `keep` последних автоматических копий; ручные не трогает."""
    autos = [m for m in list_backups() if m.get("auto")]
    for meta in autos[keep:]:
        delete(meta["path"])

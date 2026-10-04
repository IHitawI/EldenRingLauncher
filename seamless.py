"""Чтение и запись ersc_settings.ini (Seamless Co-op).

Файл правится построчно: меняются только значения нужных ключей, комментарии
и порядок строк сохраняются — так безопаснее, чем configparser.
"""
import re
from pathlib import Path

CANDIDATES = ("SeamlessCoop/ersc_settings.ini", "SeamlessCoop/seamlesscoopsettings.ini", "ersc_settings.ini")

# Известные ключи: (секция, ключ) -> (подпись, тип, подсказка, мин, макс)
KNOWN = {
    ("PASSWORD", "cooppassword"): ("Пароль сессии", "text", "Должен совпадать у всех игроков.", None, None),
    ("GAMEPLAY", "allow_invaders"): ("Вторжения других игроков", "bool", "Захватчики-ИИ из мода во время совместной игры.", None, None),
    ("GAMEPLAY", "death_debuffs"): ("Штраф за смерть", "bool", "Временное снижение максимального HP после гибели.", None, None),
    ("GAMEPLAY", "allow_summons"): ("Призыв духов", "bool", "Разрешить прах духов в совместной игре.", None, None),
    ("GAMEPLAY", "overhead_player_display"): ("Режим значка над игроками", "int", "Номер режима из описания мода; 0 — по умолчанию.", 0, 5),
    ("GAMEPLAY", "skip_splash_screens"): ("Пропуск заставок при запуске", "bool", None, None, None),
    ("GAMEPLAY", "default_boot_master_volume"): ("Громкость при запуске", "int", "0–10", 0, 10),
    ("SCALING", "enemy_health_scaling"): ("Здоровье врагов за игрока, %", "int", None, 0, 200),
    ("SCALING", "enemy_damage_scaling"): ("Урон врагов за игрока, %", "int", None, 0, 200),
    ("SCALING", "enemy_posture_scaling"): ("Стойкость врагов за игрока, %", "int", None, 0, 200),
    ("SCALING", "boss_health_scaling"): ("Здоровье боссов за игрока, %", "int", None, 0, 300),
    ("SCALING", "boss_damage_scaling"): ("Урон боссов за игрока, %", "int", None, 0, 200),
    ("SCALING", "boss_posture_scaling"): ("Стойкость боссов за игрока, %", "int", None, 0, 200),
    ("SAVE", "save_file_extension"): ("Расширение файла сохранения", "text", "По умолчанию co2 — отдельно от ванильного sl2.", None, None),
    ("LANGUAGE", "mod_language_override"): ("Язык мода", "text", "Пусто — как в игре.", None, None),
}

_SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_KEY = re.compile(r"^(\s*)([A-Za-z0-9_]+)(\s*=\s*)([^;#\r\n]*?)(\s*([;#].*)?)$")


def find_ini(game_dir) -> Path | None:
    game_dir = Path(game_dir)
    for rel in CANDIDATES:
        path = game_dir / rel
        if path.is_file():
            return path
    return None


def read(path: Path) -> list[tuple[str, str, str]]:
    """[(секция, ключ, значение)] в порядке файла."""
    section, items = "", []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _SECTION.match(line)
        if match:
            section = match.group(1).strip().upper()
            continue
        match = _KEY.match(line)
        if match and section:
            items.append((section, match.group(2), match.group(4).strip()))
    return items


def write(path: Path, values: dict) -> None:
    """values: {(СЕКЦИЯ, ключ): значение}. Создаёт резервную копию .bak."""
    text = path.read_text(encoding="utf-8", errors="replace")
    path.with_suffix(path.suffix+".bak").write_text(text, encoding="utf-8")
    section, out = "", []
    for line in text.splitlines():
        match = _SECTION.match(line)
        if match:
            section = match.group(1).strip().upper()
        else:
            key_match = _KEY.match(line)
            if key_match and (section, key_match.group(2)) in values:
                indent, key, eq, _old, tail = key_match.group(1, 2, 3, 4, 5)
                line = f"{indent}{key}{eq}{values[(section, key)]}{tail or ''}"
        out.append(line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")

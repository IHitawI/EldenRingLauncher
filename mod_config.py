"""Универсальный редактор ini-настроек модов.

Файл читается и пишется построчно: меняются только значения ключей,
комментарии, пустые строки и порядок сохраняются. Комментарий прямо над
ключом показывается в лаунчере как подсказка.
"""
import re
from pathlib import Path

_SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*$")
# Комментарий в конце строки — только после пробела: «fps = 60 ; цель».
# Значение может само начинаться с # или ; — например, цвет «= #f9fffe».
_KEY = re.compile(r"^(\s*)([^=;#\[\]\s][^=;#\[\]]*?)(\s*=\s*)(.*?)((?:\s+[;#].*)?)$")
_COMMENT = re.compile(r"^\s*[;#]\s?(.*)$")
BOOL_VALUES = {"true": "false", "false": "true", "True": "False", "False": "True", "TRUE": "FALSE", "FALSE": "TRUE"}


def _strip_quotes(value):
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'" else value


def read(path: Path) -> list[dict]:
    """[{section, key, value, hint, kind}] — kind: bool / int / float / text."""
    section, hint, items = "", [], []
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    for line in text.splitlines():
        if not line.strip():
            hint = []
            continue
        match = _SECTION.match(line)
        if match:
            section, hint = match.group(1).strip(), []
            continue
        match = _COMMENT.match(line)
        if match:
            hint.append(match.group(1).strip())
            continue
        match = _KEY.match(line)
        if match:
            raw = match.group(4).strip()
            value = _strip_quotes(raw)
            inline = (match.group(5) or "").strip().lstrip(";#").strip()
            items.append({"section": section, "key": match.group(2).strip(), "value": value,
                          "quoted": raw != value, "hint": " ".join(h for h in hint + [inline] if h)[:240],
                          "kind": _kind(value)})
            hint = []
    return items


def _kind(value):
    if value in BOOL_VALUES:
        return "bool"
    if re.fullmatch(r"-?\d+", value):
        return "int"
    if re.fullmatch(r"-?\d+\.\d+", value):
        return "float"
    return "text"


_BOOL_KEY = re.compile(r"^(enable|disable|allow|skip|show|hide|use|is|has|no|force|toggle|auto)[_A-Z]|(_enabled|Enabled)$", re.I)
_RANGE = (re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:-|–|—|\.\.|to|до)\s*(-?\d+(?:\.\d+)?)"),
          re.compile(r"min(?:imum)?\s*[:=]?\s*(-?\d+(?:\.\d+)?).{0,20}?max(?:imum)?\s*[:=]?\s*(-?\d+(?:\.\d+)?)", re.I))
_CHOICE = re.compile(r"(-?\d+)\s*[=:\-–]\s*([^,;|()\d][^,;|()]{0,40})")
_OPTIONS = re.compile(r"(?:options|values|choices|possible values|варианты)\s*[:=]\s*(.+)", re.I)


def infer(item: dict, schema: dict | None = None) -> dict:
    """Подбирает виджет для настройки: переключатель, ползунок, список вариантов,
    число или текст — по значению, комментарию и имени ключа."""
    value, hint, key = item["value"], item.get("hint", ""), item["key"]
    known = None
    if schema:
        known = schema.get((item["section"].upper(), key)) or schema.get(("", key))
    if known:
        label, kind, known_hint, lo, hi = known
        spec = {"label": label, "hint": known_hint or hint, "known": True}
        if kind == "bool":
            return {**spec, "kind": "bool01" if value in ("0", "1") else "bool"}
        if kind == "int" and lo is not None:
            return {**spec, "kind": "slider", "lo": lo, "hi": hi, "step": 1}
        return {**spec, "kind": "text" if kind == "text" else "number"}
    spec = {"label": None, "hint": hint, "known": False}
    if item["kind"] == "bool":
        return {**spec, "kind": "bool"}
    if re.fullmatch(r"#?[0-9a-fA-F]{6}", value) and (value.startswith("#") or re.search(r"colou?r|hex", key + " " + hint, re.I)):
        return {**spec, "kind": "color"}
    # Варианты из комментария: «0 = Off, 1 = Low, 2 = High» или «Options: a, b, c».
    choices = _CHOICE.findall(hint)
    if item["kind"] == "int" and len(choices) >= 2 and value in {c[0] for c in choices}:
        return {**spec, "kind": "choice", "choices": [(v, label.strip(" .")) for v, label in choices]}
    options = _OPTIONS.search(hint)
    if options and item["kind"] == "text":
        values = [o.strip(" .\"'") for o in re.split(r"[,|/]", options.group(1)) if o.strip(" .\"'")]
        if 2 <= len(values) <= 12 and value in values:
            return {**spec, "kind": "choice", "choices": [(v, v) for v in values]}
    if value in ("0", "1") and (_BOOL_KEY.search(key) or re.search(r"0\s*[=/:]\s*(off|false|disable)|1\s*[=/:]\s*(on|true|enable)|\b(on/off|0/1)\b", hint, re.I)):
        return {**spec, "kind": "bool01"}
    if item["kind"] in ("int", "float"):
        for pattern in _RANGE:
            match = pattern.search(hint)
            if match:
                lo, hi = float(match.group(1)), float(match.group(2))
                if lo < hi and lo <= float(value) <= hi and hi - lo <= 100000:
                    step = 1 if item["kind"] == "int" else max(0.01, round((hi - lo) / 100, 2))
                    return {**spec, "kind": "slider", "lo": lo, "hi": hi, "step": step, "float": item["kind"] == "float"}
        return {**spec, "kind": "number"}
    return {**spec, "kind": "text"}


def write(path: Path, values: dict) -> None:
    """values: {(секция, ключ): новое значение}. Перед записью делает .bak."""
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    path.with_suffix(path.suffix+".bak").write_text(text, encoding="utf-8")
    quoted = {(i["section"], i["key"]) for i in read(path) if i["quoted"]}
    section, out = "", []
    for line in text.splitlines():
        match = _SECTION.match(line)
        if match:
            section = match.group(1).strip()
        elif not _COMMENT.match(line):
            key_match = _KEY.match(line)
            if key_match:
                key = (section, key_match.group(2).strip())
                if key in values:
                    value = str(values[key])
                    if key in quoted:
                        value = f'"{value}"'
                    indent, name, eq, _old, tail = key_match.group(1, 2, 3, 4, 5)
                    line = f"{indent}{name}{eq}{value}{tail or ''}"
        out.append(line)
    path.write_text("\n".join(out)+"\n", encoding="utf-8")

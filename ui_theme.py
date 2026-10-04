"""Native field styles using the same tokens as the Figma scene."""
import sys
from pathlib import Path
from tkinter import ttk
from ui_tokens import PANEL, BG, TEXT, GOLD, MUTED, BORDER, FONT


def load_embedded_font(assets_root: Path):
    """Регистрирует El Messiri как приватный (per-process) шрифт из assets/fonts,
    чтобы не требовать его установки в систему. Работает только на Windows;
    на других ОС просто ничего не делает (в лаунчере используется только там)."""
    if sys.platform != "win32":
        return
    font_path = Path(assets_root) / "fonts" / "ElMessiri-Variable.ttf"
    if not font_path.is_file():
        return
    try:
        import ctypes
        FR_PRIVATE = 0x10
        ctypes.windll.gdi32.AddFontResourceExW(str(font_path), FR_PRIVATE, 0)
    except Exception:
        pass


def apply_theme(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=PANEL, foreground=TEXT, font=(FONT,-16))
    for name in ("TFrame","Card.TFrame","App.TFrame","Inner.TFrame","Side.TFrame"):
        style.configure(name, background=PANEL)
    for name in ("TLabel","CardText.TLabel","Section.TLabel","Subtitle.TLabel","CardMuted.TLabel"):
        style.configure(name, background=PANEL, foreground=MUTED if "Muted" in name or "Subtitle" in name else TEXT,
                        font=(FONT,-16,"bold") if name == "Section.TLabel" else (FONT,-16))
    style.configure("TButton", background="#28241d", foreground=TEXT, bordercolor=BORDER, padding=(14,8), focusthickness=1, focuscolor=GOLD)
    style.map("TButton",background=[("active","#403728"),("disabled",PANEL)],foreground=[("disabled",MUTED)])
    for name in ("Gold.TButton","Accent.TButton","Side.TButton"):
        style.configure(name,background="#403728",foreground=GOLD)
    style.configure("TCheckbutton",background=PANEL,foreground=TEXT,indicatorbackground="#26231d",indicatorforeground=GOLD, padding=4)
    style.map("TCheckbutton",background=[("active",PANEL)],indicatorbackground=[("selected","#52432c")])
    style.configure("TEntry",fieldbackground="#13120f",foreground=TEXT,insertcolor=TEXT,bordercolor=BORDER,padding=6)
    style.configure("TCombobox",fieldbackground="#13120f",background=PANEL,foreground=TEXT,arrowcolor=GOLD,bordercolor=BORDER)
    style.map("TCombobox",fieldbackground=[("readonly","#13120f")],foreground=[("readonly",TEXT)])
    style.configure("Horizontal.TScale",background=PANEL,troughcolor="#373127",bordercolor=PANEL,lightcolor=GOLD,darkcolor=BORDER)
    for name in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(name, background="#3a3328", troughcolor="#11100d", arrowcolor=GOLD, bordercolor="#11100d",
                        lightcolor="#3a3328", darkcolor="#3a3328", gripcount=0, arrowsize=12)
        style.map(name, background=[("active", "#55493a"), ("pressed", "#6b5a3a")])

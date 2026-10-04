"""Layered Figma artwork with live controls and a persistent operation dock."""
import math
import random
import time
import tkinter as tk
from tkinter import ttk, font as tkfont
from PIL import ImageTk
import profiles
import versions
import ui_draw
import app_info
from ui_tokens import (BG, PANEL, GOLD, TEXT, MUTED, BORDER, SELECTED, FONT, FAQ, FAQ_EN, FAQ_GREETINGS, FAQ_GREETINGS_EN,
                       FAQ_POSES, ASSISTANT_QUIPS, NAV_HEIGHT, DOCK_HEIGHT,
                       PAGE_BG, CARD, CARD_HOVER, CARD_SELECTED, CARD_BORDER, INK, DIM, OK, WARN, OFF, t)

# Реплики ассистента на главной: подсказки при наведении и реакции на события.
HOME_TIPS = {
    "ru": ("Нужна помощь? Щёлкни по мне — открою FAQ.",
           "Ctrl+Tab — следующая вкладка, F1 — FAQ.",
           "Перед каждым запуском я делаю копию сохранений.",
           "ПКМ по профилю в библиотеке — обложка, моды и прочее.",
           "Во вкладке «Сохранения» можно вернуть любую копию."),
    "en": ("Need help? Click me — I'll open the FAQ.",
           "Ctrl+Tab — next tab, F1 — FAQ.",
           "I back up your saves before every launch.",
           "Right-click a profile in the library — cover, mods and more.",
           "The «Saves» tab can bring back any backup."),
}
CONTEXT_LINES = {
    "ru": {"drink": "Качаем… я пока выпью чаю.", "dizzy": "Ой. Что-то сломалось — загляни в журнал.",
           "confused": "Начни с «Добавить игру» — я поищу её в Steam.", "sleep": "Хррр… (щёлкни, если нужна помощь)"},
    "en": {"drink": "Downloading… I'll have some tea meanwhile.", "dizzy": "Oops. Something broke — check the log.",
           "confused": "Start with «Add game» — I'll look for it in Steam.", "sleep": "Zzz… (click me if you need help)"},
}
REACTION_LINES = {
    "ru": {"smug": "Готово. Я молодец.", "bonfire": "Удачной охоты, Погасший!", "angry": "Конфликты! Разберись с модами.",
           "dizzy": "Ой… что-то пошло не так.", "silent": "…"},
    "en": {"smug": "Done. I'm great.", "bonfire": "Good hunting, Tarnished!", "angry": "Conflicts! Sort out your mods.",
           "dizzy": "Oops… something went wrong.", "silent": "…"},
}
from ui_media import Assets, Background


TABS = ("home", "library", "mods", "saves", "faq", "settings")


def has_focus(widget):
    """Есть ли фокус у виджета. focus_get() падает с KeyError, когда фокус во
    внутреннем окне Tk (например, в выпадающем списке ttk.Combobox), поэтому
    сравниваем имена окон напрямую."""
    try:
        return str(widget.tk.call("focus")) == str(widget)
    except tk.TclError:
        return False


def elide(text, font, max_width, middle=False):
    """Обрезает строку многоточием, чтобы она влезла в max_width пикселей.
    middle=True оставляет начало и конец — удобно для путей."""
    if max_width <= 0 or font.measure(text) <= max_width:
        return text
    ellipsis = "…"
    if middle:
        left, right = text[:len(text)//2], text[len(text)//2:]
        while left and right and font.measure(left+ellipsis+right) > max_width:
            if len(left) >= len(right):
                left = left[:-1]
            else:
                right = right[1:]
        return left+ellipsis+right
    while text and font.measure(text+ellipsis) > max_width:
        text = text[:-1]
    return text+ellipsis


class TabFrame(tk.Frame):
    def title(self, _text):
        pass

    def geometry(self, _value):
        pass


class ToggleSwitch(tk.Canvas):
    """Тумблер со сглаженной графикой и плавным ходом ручки."""

    def __init__(self, parent, variable, command=None, width=50, height=26):
        super().__init__(parent, width=width, height=height, bg=parent["bg"],
                         highlightthickness=0, borderwidth=0, cursor="hand2", takefocus=True)
        self.variable, self.command, self.width, self.height = variable, command, width, height
        self.hot = False
        self.pos = 1.0 if variable.get() else 0.0
        self.anim_job = None
        self.bind("<Enter>", lambda _e: self._set_hot(True))
        self.bind("<Leave>", lambda _e: self._set_hot(False))
        self.bind("<Button-1>", self._toggle)
        self.bind("<space>", self._toggle)
        self.bind("<Return>", self._toggle)
        self.bind("<FocusIn>", lambda _e: self._draw())
        self.bind("<FocusOut>", lambda _e: self._draw())
        self.trace = variable.trace_add("write", lambda *_a: self._animate())
        self.bind("<Destroy>", self._cleanup)
        self._draw()

    def _cleanup(self, _e=None):
        try:
            self.variable.trace_remove("write", self.trace)
        except (tk.TclError, ValueError):
            pass

    def _set_hot(self, hot):
        self.hot = hot
        self._draw()

    def _toggle(self, _e=None):
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()
        return "break"

    def _animate(self):
        if not self.winfo_exists():
            return
        target = 1.0 if self.variable.get() else 0.0
        self.pos += (target-self.pos)*0.4
        if abs(target-self.pos) < 0.02:
            self.pos = target
            self.anim_job = None
        else:
            self.anim_job = self.after(14, self._animate)
        self._draw()

    def _draw(self):
        if not self.winfo_exists():
            return
        self.delete("all")
        on = bool(self.variable.get())
        w, h = self.width, self.height
        if on:
            track, outline = ("#a67f3a" if self.hot else "#8d6b30"), "#b8944f"
        else:
            track, outline = ("#2b2720" if self.hot else "#211e18"), ("#6e6350" if self.hot else "#4a4234")
        if has_focus(self):
            outline = GOLD
        self.create_image(0, 0, anchor="nw", image=ui_draw.pill(w, h, track, outline, 1))
        d = h-8
        x = 4+self.pos*(w-8-d)
        knob = ui_draw.circle(d, "#ffe7b5" if on else ("#d8ccb4" if self.hot else "#bfb39b"), glow="#000000", glow_size=3)
        self.create_image(x-3, 1, anchor="nw", image=knob)


class Slider(tk.Canvas):
    """Ползунок: тонкая дорожка, золотая заливка до ручки, ручка со свечением
    при наведении. Поддерживает перетаскивание, щелчок, стрелки и Home/End."""

    H, KNOB, TRACK = 30, 18, 6

    def __init__(self, parent, variable, lo, hi, step=1, command=None):
        super().__init__(parent, height=self.H, bg=parent["bg"], highlightthickness=0, borderwidth=0,
                         cursor="hand2", takefocus=True)
        self.variable, self.lo, self.hi, self.step, self.command = variable, lo, hi, step, command
        self.hot = self.dragging = False
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Enter>", lambda _e: self._set_hot(True))
        self.bind("<Leave>", lambda _e: self._set_hot(False))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", lambda e: self._set_from_x(e.x))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Left>", lambda _e: self._nudge(-1))
        self.bind("<Right>", lambda _e: self._nudge(1))
        self.bind("<Home>", lambda _e: self._set_value(self.lo))
        self.bind("<End>", lambda _e: self._set_value(self.hi))
        self.bind("<FocusIn>", lambda _e: self._draw())
        self.bind("<FocusOut>", lambda _e: self._draw())
        self.trace = variable.trace_add("write", lambda *_a: self._draw())
        self.bind("<Destroy>", self._cleanup)

    def _cleanup(self, _e=None):
        try:
            self.variable.trace_remove("write", self.trace)
        except (tk.TclError, ValueError):
            pass

    def _pad(self):
        return self.KNOB/2+6

    def _set_hot(self, hot):
        self.hot = hot
        self._draw()

    def _press(self, e):
        self.focus_set()
        self.dragging = True
        self._set_from_x(e.x)

    def _release(self, _e=None):
        self.dragging = False
        self._draw()

    def _nudge(self, direction):
        self._set_value(float(self.variable.get())+direction*self.step)
        return "break"

    def _set_from_x(self, x):
        pad, w = self._pad(), max(1, self.winfo_width()-2*self._pad())
        self._set_value(self.lo+(x-pad)/w*(self.hi-self.lo))

    def _set_value(self, value):
        value = round(value/self.step)*self.step
        value = max(self.lo, min(self.hi, value))
        if value != self.variable.get():
            self.variable.set(int(value) if float(value).is_integer() else value)
            if self.command:
                self.command(value)
        return "break"

    def _draw(self):
        if not self.winfo_exists():
            return
        self.delete("all")
        w = self.winfo_width()
        if w < 40:
            return
        pad, cy = self._pad(), self.H/2
        span = w-2*pad
        ratio = (float(self.variable.get())-self.lo)/max(1e-9, self.hi-self.lo)
        x = pad+span*max(0.0, min(1.0, ratio))
        self.create_image(pad-3, cy-self.TRACK/2, anchor="nw", image=ui_draw.pill(span+6, self.TRACK, "#2a251d", "#3a3328"))
        fill_w = x-pad+6
        if fill_w > self.TRACK:
            self.create_image(pad-3, cy-self.TRACK/2, anchor="nw", image=ui_draw.pill(fill_w, self.TRACK, "#b8904c"))
        lit = self.hot or self.dragging or has_focus(self)
        glow = 6
        knob = ui_draw.circle(self.KNOB, "#ffe1a6" if lit else "#e9cf98", outline="#7a5f33", width=1.5,
                              glow=GOLD if lit else "#000000", glow_size=glow)
        self.create_image(x-self.KNOB/2-glow, cy-self.KNOB/2-glow, anchor="nw", image=knob)


class ScrollFrame(tk.Frame):
    """Прокручиваемая область для вкладок: полоса появляется, только если
    содержимое не помещается (например, в окне 960×740)."""

    def __init__(self, parent, bg):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, borderwidth=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.window = self.canvas.create_window(0, 0, anchor="nw", window=self.inner)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", self._update)
        self.canvas.bind("<Configure>", self._update)
        self.bind_all("<MouseWheel>", self._wheel)

    def _update(self, _e=None):
        self.canvas.itemconfigure(self.window, width=self.canvas.winfo_width())
        needed, height = self.inner.winfo_reqheight(), self.canvas.winfo_height()
        self.canvas.configure(scrollregion=(0, 0, 0, max(needed, height)))
        if needed > height+1 and not self.bar.winfo_ismapped():
            self.bar.pack(side="right", fill="y", before=self.canvas)
        elif needed <= height+1 and self.bar.winfo_ismapped():
            self.bar.pack_forget()
            self.canvas.yview_moveto(0)

    def _wheel(self, e):
        try:
            if not self.winfo_exists() or not self.bar.winfo_ismapped():
                return
            widget = self.winfo_containing(e.x_root, e.y_root)
        except (tk.TclError, KeyError):
            return
        while widget is not None and widget is not self:
            widget = widget.master
        if widget is self:
            self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")


class TextureButton(tk.Canvas):
    """Кнопка на текстуре install-default/install-hover.png для классических
    вкладок (Библиотека/Моды/Настройки), которые рисуются обычными Tk-виджетами,
    а не в сцене на канвасе — чтобы они визуально совпадали с остальным лаунчером."""

    def __init__(self, parent, assets, text, command, width=176, height=52, small=False, tooltip=None):
        super().__init__(parent, width=width, height=height, bg=parent["bg"],
                         highlightthickness=0, borderwidth=0, cursor="hand2", takefocus=True)
        self.assets, self.command, self.hot, self.enabled = assets, command, False, True
        self.width, self.height = width, height
        self.default_img = assets.photo("buttons/install-default.png", (width, height), False)
        self.hover_img = assets.photo("buttons/install-hover.png", (width, height), False)
        self.image_id = self.create_image(0, 0, anchor="nw", image=self.default_img)
        self.font = tkfont.Font(self, family=FONT, size=-(13 if small else 15), weight="bold")
        self.text_id = self.create_text(width/2, height/2, text="", fill=TEXT, font=self.font)
        self.set_text(text)
        self.bind("<Enter>", lambda _e: self._set(True))
        self.bind("<Leave>", lambda _e: self._set(False))
        self.bind("<Button-1>", self._click)
        self.bind("<Return>", self._click)
        self.bind("<space>", self._click)
        self.bind("<FocusIn>", lambda _e: self._set(self.hot))
        self.bind("<FocusOut>", lambda _e: self._set(self.hot))
        if tooltip:
            Tooltip(self, tooltip)

    def set_text(self, text):
        self.itemconfigure(self.text_id, text=elide(text, self.font, self.width-30))

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.configure(cursor="hand2" if enabled else "")
        self._set(self.hot)

    def _click(self, _e=None):
        if self.enabled:
            self.command()
        return "break"

    def _set(self, hot):
        self.hot = hot
        lit = self.enabled and (hot or has_focus(self))
        self.itemconfigure(self.image_id, image=self.hover_img if lit else self.default_img)
        self.itemconfigure(self.text_id, fill=GOLD if lit else TEXT if self.enabled else OFF)


class Tooltip:
    """Небольшая подсказка при наведении на виджет."""

    def __init__(self, widget, text):
        self.widget, self.text, self.window, self.job = widget, text, None, None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._cancel()
        self.job = self.widget.after(550, self._show)

    def _cancel(self):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None

    def _show(self):
        self.job = None
        if self.window or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx()+12
        y = self.widget.winfo_rooty()+self.widget.winfo_height()+6
        self.window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(tw, text=self.text, bg="#0f0e0b", fg=INK, font=(FONT, -13), padx=10, pady=6,
                 highlightthickness=1, highlightbackground=CARD_BORDER, justify="left", wraplength=360).pack()

    def _hide(self, _e=None):
        self._cancel()
        if self.window:
            self.window.destroy()
            self.window = None


class CardList(tk.Canvas):
    """Прокручиваемый список карточек: статус-точка, заголовок, подпись,
    бейдж и мета-текст справа. Заменяет голый tk.Listbox на вкладках."""

    ROW_H, GAP, SCROLL_W = 64, 8, 10

    def __init__(self, parent, on_select=None, on_activate=None, on_context=None, empty_text="", empty_image=None):
        super().__init__(parent, bg=parent["bg"], highlightthickness=0, borderwidth=0, takefocus=True)
        self.on_select, self.on_activate, self.on_context = on_select, on_activate, on_context
        self.empty_text, self.empty_image = empty_text, empty_image
        self.rows, self.selected, self.hover, self.offset, self.max_offset = [], None, None, 0.0, 0.0
        self.keyboard = False  # рамку фокуса показываем только при работе с клавиатуры
        self.f_title = tkfont.Font(self, family=FONT, size=-17, weight="bold")
        self.f_sub = tkfont.Font(self, family=FONT, size=-13)
        self.f_badge = tkfont.Font(self, family=FONT, size=-11, weight="bold")
        self.f_meta = tkfont.Font(self, family=FONT, size=-12)
        self.bind("<Configure>", lambda _e: self.draw())
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", self._leave)
        self.bind("<Enter>", self._enter)
        self.bind("<Button-1>", self._click)
        self.bind("<Double-Button-1>", self._double)
        self.bind("<Button-3>", self._context)
        self.bind("<Up>", lambda _e: self._step(-1))
        self.bind("<Down>", lambda _e: self._step(1))
        self.bind("<Return>", lambda _e: self._fire_activate())
        self.bind("<FocusIn>", lambda _e: self.draw())
        self.bind("<FocusOut>", lambda _e: self.draw())

    def set_rows(self, rows, selected=None):
        self.rows = list(rows)
        if selected is not None and 0 <= selected < len(self.rows):
            self.selected = selected
        elif self.selected is not None and self.selected >= len(self.rows):
            self.selected = len(self.rows)-1 if self.rows else None
        self.draw()
        if self.selected is not None:
            self.see(self.selected)

    def select(self, index, notify=True):
        if index is None or not (0 <= index < len(self.rows)):
            return
        self.selected = index
        self.see(index)
        self.draw()
        if notify and self.on_select:
            self.on_select(index)

    def see(self, index):
        h = self.winfo_height()
        if h < 10:
            return
        top = index*(self.ROW_H+self.GAP)
        if top < self.offset:
            self.offset = top
        elif top+self.ROW_H > self.offset+h:
            self.offset = top+self.ROW_H-h
        self.draw()

    def _index_at(self, y):
        pos = y+self.offset
        index = int(pos // (self.ROW_H+self.GAP))
        if 0 <= index < len(self.rows) and pos-index*(self.ROW_H+self.GAP) <= self.ROW_H:
            return index
        return None

    def _motion(self, e):
        index = self._index_at(e.y)
        if index != self.hover:
            self.hover = index
            self.configure(cursor="hand2" if index is not None else "")
            self.draw()

    def _enter(self, _e=None):
        self.bind_all("<MouseWheel>", self._wheel)

    def _leave(self, _e=None):
        self.unbind_all("<MouseWheel>")
        if self.hover is not None:
            self.hover = None
            self.draw()

    def _wheel(self, e):
        self.offset = max(0, min(self.max_offset, self.offset-(1 if e.delta > 0 else -1)*(self.ROW_H+self.GAP)/1.5))
        self.draw()

    def _click(self, e):
        self.focus_set()
        self.keyboard = False
        index = self._index_at(e.y)
        if index is not None:
            self.select(index)

    def _double(self, e):
        index = self._index_at(e.y)
        if index is not None:
            self.select(index, notify=False)
            self._fire_activate()

    def _context(self, e):
        index = self._index_at(e.y)
        if index is not None:
            self.select(index)
            if self.on_context:
                self.on_context(e)

    def _step(self, direction):
        self.keyboard = True
        if not self.rows:
            return "break"
        current = -1 if self.selected is None else self.selected
        self.select(max(0, min(len(self.rows)-1, current+direction)))
        return "break"

    def _fire_activate(self):
        if self.selected is not None and self.on_activate:
            self.on_activate(self.selected)
        return "break"

    def draw(self):
        if not self.winfo_exists():
            return
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 40:
            return
        if not self.rows:
            # Пустой список: ассистент и подсказка по центру.
            text_y = min(h/2, 90)
            if self.empty_image is not None:
                ih = self.empty_image.height()
                top = max(10, (h-ih-60)/2)
                self.create_image(w/2, top, anchor="n", image=self.empty_image)
                text_y = top+ih+14
            self.create_text(w/2, text_y, text=self.empty_text, fill=DIM, font=self.f_sub,
                             width=max(200, w-80), justify="center", anchor="n")
            return
        content_h = len(self.rows)*(self.ROW_H+self.GAP)-self.GAP
        self.max_offset = max(0, content_h-h)
        self.offset = max(0, min(self.offset, self.max_offset))
        right = w-(self.SCROLL_W+4 if self.max_offset else 0)
        focused = has_focus(self) and self.keyboard
        for index, row in enumerate(self.rows):
            y = index*(self.ROW_H+self.GAP)-self.offset
            if y+self.ROW_H < 0 or y > h:
                continue
            selected, hot = index == self.selected, index == self.hover
            fill = CARD_SELECTED if selected else CARD_HOVER if hot else CARD
            outline = GOLD if selected and focused else "#7a6640" if selected else "#4a4234" if hot else CARD_BORDER
            # Вложенная строка (часть модпака): отступ и линия-связка слева.
            ind = 34 if row.get("indent") else 0
            if ind:
                self.create_line(16, y-self.GAP, 16, y+self.ROW_H/2, fill="#4a4234", width=2)
                self.create_line(16, y+self.ROW_H/2, ind-4, y+self.ROW_H/2, fill="#4a4234", width=2)
            self.create_image(ind, y, anchor="nw", image=ui_draw.rounded(right-ind, self.ROW_H, 6, fill, outline, 1))
            if selected:
                self.create_image(ind+1, y+12, anchor="nw", image=ui_draw.pill(4, self.ROW_H-24, GOLD))
            status = row.get("status", OFF)
            self.create_image(ind+14, y+self.ROW_H/2-8, anchor="nw",
                              image=ui_draw.circle(10, status, glow=status if status != OFF else None, glow_size=3))
            text_x = ind+40
            if row.get("cover") is not None:
                self.create_image(36, y+(self.ROW_H-44)/2, anchor="nw", image=row["cover"])
                text_x = 92
            # Справа: бейдж и мета-строка — считаем ширину заранее, чтобы
            # заголовок и путь обрезались, а не наезжали на них.
            badge = row.get("badge", "")
            badge_w = self.f_badge.measure(badge)+18 if badge else 0
            meta = row.get("meta", "")
            meta_w = self.f_meta.measure(meta) if meta else 0
            side_w = max(badge_w, meta_w)
            text_w = right-text_x-side_w-28
            self.create_text(text_x, y+13, anchor="nw", text=elide(row.get("title", ""), self.f_title, text_w),
                             fill=GOLD if selected else INK if not row.get("dim") else DIM, font=self.f_title)
            self.create_text(text_x, y+38, anchor="nw", text=elide(row.get("subtitle", ""), self.f_sub, text_w, middle=True),
                             fill=DIM, font=self.f_sub)
            if badge:
                bx = right-16-badge_w
                self.create_image(bx, y+12, anchor="nw", image=ui_draw.pill(
                    badge_w, 20, "#16140f", "#8a7550" if selected else CARD_BORDER))
                self.create_text(bx+badge_w/2, y+22, text=badge, fill=GOLD if selected else MUTED, font=self.f_badge)
            if meta:
                self.create_text(right-16, y+38, anchor="ne", text=meta, fill=row.get("meta_color", DIM), font=self.f_meta)
        if self.max_offset:
            track_x = w-self.SCROLL_W/2-4
            self.create_image(track_x, 2, anchor="nw", image=ui_draw.pill(4, h-4, "#2a261f"))
            thumb_h = max(28, h*h/content_h)
            thumb_y = (h-thumb_h)*(self.offset/self.max_offset)
            self.create_image(track_x, thumb_y+2, anchor="nw", image=ui_draw.pill(4, thumb_h-4, BORDER))


def page_section(parent, title, hint=None, expand=False, padx=20):
    """Карточка-раздел на вкладке: заголовок, необязательная подсказка, тело."""
    wrap = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=CARD_BORDER)
    wrap.pack(fill="both" if expand else "x", expand=expand, padx=padx, pady=(0, 14))
    inner = tk.Frame(wrap, bg=CARD)
    inner.pack(fill="both", expand=True, padx=20, pady=14)
    tk.Label(inner, text=title, bg=CARD, fg=GOLD, font=(FONT, -17, "bold")).pack(anchor="w")
    if hint:
        label = tk.Label(inner, text=hint, bg=CARD, fg=DIM, font=(FONT, -13), justify="left", anchor="w")
        label.pack(anchor="w", fill="x", pady=(2, 0))
        label.bind("<Configure>", lambda e: label.configure(wraplength=max(200, e.width-4)))
    return inner


def toggle_row(parent, label, variable, hint=None, command=None):
    row = tk.Frame(parent, bg=parent["bg"])
    row.pack(fill="x", pady=(10, 0))
    switch = ToggleSwitch(row, variable, command)
    switch.pack(side="right", padx=(12, 0))
    text_col = tk.Frame(row, bg=parent["bg"])
    text_col.pack(side="left", fill="x", expand=True)
    title = tk.Label(text_col, text=label, bg=parent["bg"], fg=INK, font=(FONT, -15), anchor="w", justify="left", cursor="hand2")
    title.pack(anchor="w", fill="x")
    title.bind("<Button-1>", switch._toggle)
    title.bind("<Configure>", lambda e: title.configure(wraplength=max(160, e.width-4)))
    if hint:
        sub = tk.Label(text_col, text=hint, bg=parent["bg"], fg=DIM, font=(FONT, -12), anchor="w", justify="left")
        sub.pack(anchor="w", fill="x")
        sub.bind("<Configure>", lambda e: sub.configure(wraplength=max(160, e.width-4)))
    return switch


def slider_row(parent, variable, lo, hi, label, value_fmt, step=1, hint=None):
    """Подпись слева, текущее значение золотом справа, под ними — ползунок."""
    bg = parent["bg"]
    row = tk.Frame(parent, bg=bg)
    row.pack(fill="x", pady=(16, 0))
    top = tk.Frame(row, bg=bg)
    top.pack(fill="x")
    tk.Label(top, text=label, bg=bg, fg=INK, font=(FONT, -15)).pack(side="left")
    value = tk.Label(top, text=value_fmt(variable.get()), bg=bg, fg=GOLD, font=(FONT, -15, "bold"))
    value.pack(side="right")
    if hint:
        tk.Label(row, text=hint, bg=bg, fg=DIM, font=(FONT, -12), anchor="w").pack(anchor="w", fill="x")
    slider = Slider(row, variable, lo, hi, step)
    slider.pack(fill="x", pady=(2, 0))
    trace = variable.trace_add("write", lambda *_a: value.winfo_exists() and value.configure(text=value_fmt(variable.get())))
    value.bind("<Destroy>", lambda _e: _safe_trace_remove(variable, trace))
    scale = tk.Frame(row, bg=bg)
    scale.pack(fill="x")
    tk.Label(scale, text=value_fmt(lo), bg=bg, fg="#5f574a", font=(FONT, -11)).pack(side="left", padx=(4, 0))
    tk.Label(scale, text=value_fmt(hi), bg=bg, fg="#5f574a", font=(FONT, -11)).pack(side="right", padx=(0, 4))
    return slider


def _safe_trace_remove(variable, trace):
    try:
        variable.trace_remove("write", trace)
    except (tk.TclError, ValueError):
        pass


def styled_entry(parent, variable, width=24):
    return tk.Entry(parent, textvariable=variable, width=width, bg="#12110e", fg=INK, insertbackground=GOLD,
                    relief="flat", highlightthickness=1, highlightbackground=CARD_BORDER, highlightcolor=GOLD,
                    font=(FONT, -15), selectbackground="#4a3c20", selectforeground="#fff5d3")


class SceneValue:
    """Adapter retaining the existing download callback contract."""
    def __init__(self, scene, text=""):
        self.scene, self.text = scene, text
        self.value, self.mode, self.enabled = 0., "determinate", True

    def configure(self, cnf=None, **kwargs):
        for key in ("text", "value", "mode"):
            if key in kwargs:
                setattr(self, key, kwargs[key])
        if "state" in kwargs:
            self.enabled = kwargs["state"] != "disabled"
        self.scene.schedule()

    config = configure

    def set_text(self, value):
        self.configure(text=value)

    def start(self, _interval=12):
        self.configure(mode="indeterminate")

    def stop(self):
        self.configure(mode="determinate")


def version_caption(name):
    info = versions.get(name) or {}
    date = info.get("release_date")
    if not date:
        return name
    year, month, day = date.split("-")
    return f"{name}   ·   {day}.{month}.{year}"


class VersionPicker(SceneValue):
    def __init__(self, scene, variable):
        super().__init__(scene)
        self.variable, self.panel = variable, None
        self.bounds = (0, 0, 220, 44)

    def toggle(self):
        if self.panel:
            return self.close()
        if not self.enabled:
            return
        x, y, w, h = self.bounds
        values = versions.names()
        popup_w = max(w, 340)
        popup_h = min(330, max(80, len(values)*30+16))
        self.panel = panel = tk.Frame(self.scene.master, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        panel.place(x=x, y=max(NAV_HEIGHT+8, y-popup_h-8), width=popup_w, height=popup_h)
        box = tk.Listbox(panel, bg=PANEL, fg=TEXT, selectbackground="#454035", selectforeground=GOLD,
                         font=(FONT, -16), borderwidth=0, highlightthickness=0, activestyle="none", exportselection=False)
        scroll = ttk.Scrollbar(panel, command=box.yview)
        scroll.pack(side="right", fill="y")
        box.configure(yscrollcommand=scroll.set)
        box.pack(fill="both", expand=True, padx=8, pady=8)
        self.listbox = box
        for name in values:
            label = version_caption(name)
            box.insert("end", label if versions.get(name).get("available", True) else label+" · нет манифестов")
        if self.variable.get() in values:
            index = values.index(self.variable.get())
            box.selection_set(index)
            box.activate(index)
            box.see(index)

        def choose(_event=None):
            selected = box.curselection()
            if selected:
                self.variable.set(values[selected[0]])
            self.close()
            return "break"
        box.bind("<ButtonRelease-1>", choose)
        box.bind("<Return>", choose)
        box.bind("<Escape>", lambda _e: self.close())
        box.bind("<Tab>", lambda _e: self.close())
        box.focus_set()
        panel.lift()
        self.scene.schedule()

    def close(self):
        if self.panel:
            self.panel.destroy()
            self.panel = None
            self.scene.focus_set()
            self.scene.focus_key = "version"
            self.scene.schedule()
        return "break"


class LauncherScene(tk.Canvas):
    def __init__(self, app, master):
        super().__init__(master, bg=BG, highlightthickness=0, takefocus=True)
        self.app, self.assets, self.active = app, Assets(), "home"
        self.lang = app.data.get("settings", {}).get("lang", "ru")
        self.regions, self.photos, self.fonts = [], [], {}
        self.background_photo = None
        self.background_item = self.create_image(0, 0, anchor="nw")
        self.hover_key = self.focus_key = self.pressed_key = self.job = None
        self.faq_index, self.phase = 0, 0
        self.faq_scroll, self.faq_scroll_target, self.faq_list_bounds = 0.0, 0.0, None
        self.faq_scroll_max = 0.0
        # FAQ-диалог: приветствие до выбора вопроса, «печать» ответа и
        # лёгкое покачивание персонажа.
        self.faq_intro, self.faq_greeting = True, FAQ_GREETINGS[0]
        self.faq_typed, self.faq_answer_full, self.faq_answer_id = 0, "", None
        self.guide_phase, self.guide_offset = 0.0, 0.0
        self.keyboard_nav = False
        self.toast_text, self.toast_job = None, None
        # Ассистент IWaithI: текущая поза, временная реакция, «пружинка» при
        # смене позы, прыжок по щелчку и засыпание при бездействии.
        self.shown_pose, self.reaction, self.reaction_until, self.reaction_text = None, None, 0.0, None
        self.pop_start, self.hop_start = 0.0, 0.0
        self.last_input = time.monotonic()
        self.faq_quip = None
        self.tip_index = 0
        self.sprite_cache = {}
        self.bind("<Key>", self._key)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda _e: self._hover(None))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Button-4>", lambda e: self._wheel(e, delta=1))
        self.bind("<Button-5>", lambda e: self._wheel(e, delta=-1))
        self.bind("<Tab>", lambda _e: self._focus_next(1))
        self.bind("<Shift-Tab>", lambda _e: self._focus_next(-1))
        self.bind("<Return>", self._activate)
        self.bind("<space>", self._activate)
        self.bind("<Escape>", self._escape)
        self.bind("<Left>", lambda _e: self._arrow(-1))
        self.bind("<Right>", lambda _e: self._arrow(1))
        self.bind("<Up>", lambda _e: self._arrow(-1, vertical=True))
        self.bind("<Down>", lambda _e: self._arrow(1, vertical=True))
        for event in ("<FocusIn>", "<FocusOut>", "<Configure>"):
            self.bind(event, lambda _e: self.schedule())
        self.animation_job = self.after(80, self._tick)

    def font(self, size, bold=False):
        key = (int(size), bold)
        if key not in self.fonts:
            self.fonts[key] = tkfont.Font(self, family=FONT, size=-int(size), weight="bold" if bold else "normal")
        return self.fonts[key]

    def text(self, x, y, value, size=18, color=TEXT, anchor="nw", width=None, bold=False, **extra):
        kwargs = dict(text=value, font=self.font(size, bold), fill=color, anchor=anchor, tags="ui")
        if width:
            kwargs["width"] = int(width)
        return self.create_text(x, y, **kwargs, **extra)

    def asset(self, name, x, y, w, h, contain=True, mirror=False, tint=None, tag=None):
        image = self.assets.photo(name, (w, h), contain, mirror, tint)
        self.photos.append(image)
        return self.create_image(x+w/2, y+h/2, image=image, tags=("ui", tag) if tag else "ui")

    def image(self, photo, x, y, anchor="nw"):
        """Сглаженный примитив из ui_draw (кэшируется там же)."""
        return self.create_image(x, y, image=photo, anchor=anchor, tags="ui")

    def region(self, key, bounds, command, enabled=True):
        if enabled:
            self.regions.append((key, bounds, command))
        # Рамка фокуса — только при управлении с клавиатуры, чтобы после
        # щелчка мышью на кнопке не «залипал» пунктир.
        if key == self.focus_key and has_focus(self) and enabled and self.keyboard_nav:
            x, y, w, h = bounds
            self.image(ui_draw.rounded(w+10, h+10, 10, None, GOLD, 1.5), x-5, y-5)

    def toast(self, text, seconds=2.6):
        """Короткое уведомление под навигацией (скопировано, запущено и т. п.).
        Если открыта вкладка, она закрывает эту область — тогда сообщение
        временно показывается в строке статуса нижней панели."""
        if self.app.page_host.winfo_ismapped():
            status = self.app.status
            previous = getattr(self, "_status_before_toast", None) or status.text
            self._status_before_toast = previous
            status.configure(text=text)

            def restore():
                if status.text == text:
                    status.configure(text=previous)
                self._status_before_toast = None
            if self.toast_job:
                self.after_cancel(self.toast_job)
            self.toast_text = None
            self.toast_job = self.after(int(seconds*1000), restore)
            return
        self.toast_text = text
        if self.toast_job:
            self.after_cancel(self.toast_job)
        self.toast_job = self.after(int(seconds*1000), self._hide_toast)
        self.schedule()

    def _hide_toast(self):
        self.toast_text, self.toast_job = None, None
        self.schedule()

    def draw_toast(self, w):
        if not self.toast_text:
            return
        f = self.font(15, True)
        tw = f.measure(self.toast_text)+58
        x, y = (w-tw)/2, NAV_HEIGHT+14
        self.image(ui_draw.pill(tw, 38, "#1d1a14", "#7a6640", 1, alpha=240), x, y)
        self.image(ui_draw.circle(8, GOLD, glow=GOLD, glow_size=3), x+16, y+12)
        self.text(x+36, y+19, self.toast_text, 15, INK, "w", bold=True)

    def button(self, key, label, bounds, command, enabled=True):
        x, y, w, h = bounds
        hot = enabled and key in (self.hover_key, self.focus_key)
        self.asset("buttons/install-hover.png" if hot else "buttons/install-default.png", x, y, w, h, False)
        size = min(24, max(17, int(h*.34)))
        while self.font(size, True).measure(label) > w-42 and size > 13:
            size -= 1
        self.text(x+w/2, y+h/2+(1 if key == self.pressed_key else 0), label, size,
                  GOLD if hot else TEXT if enabled else MUTED, "center", bold=True)
        self.region(key, bounds, command, enabled)

    def link(self, key, label, bounds, command, enabled=True, size=16):
        x, y, w, h = bounds
        self.text(x+w/2, y+h/2, label, size, GOLD if key in (self.hover_key, self.focus_key) else MUTED, "center", bold=True)
        self.region(key, bounds, command, enabled)

    # ── ассистент IWaithI ─────────────────────────────────────────────

    def sprite_photo(self, pose, height):
        """Спрайт позы для обычных Tk-виджетов (пустые состояния вкладок)."""
        key = (pose, int(height))
        if key not in self.sprite_cache:
            from PIL import Image, ImageOps
            with Image.open(self.assets.root/"characters"/"chibi"/f"{pose}.png") as source:
                image = ImageOps.contain(source.convert("RGBA"), (int(height*1.5), int(height)), Image.Resampling.LANCZOS)
            self.sprite_cache[key] = ImageTk.PhotoImage(image)
        return self.sprite_cache[key]

    def react(self, pose, seconds=3.5, text=None):
        """Временная эмоция ассистента (готово, ошибка, запуск игры…)."""
        self.reaction, self.reaction_until = pose, time.monotonic()+seconds
        self.reaction_text = text if text is not None else REACTION_LINES[self.lang].get(pose)
        self.after(int(seconds*1000)+30, self.schedule)
        self.schedule()

    def _idle(self):
        return time.monotonic()-self.last_input

    def current_pose(self, context):
        now = time.monotonic()
        if self.reaction and now < self.reaction_until:
            return self.reaction
        if context == "faq":
            if self.faq_quip:
                return self.faq_quip[0]
            if self._idle() > 40:
                return "sleep"
            return "wall" if self.faq_intro else FAQ_POSES[self.faq_index % len(FAQ_POSES)]
        if getattr(self.app, "operation_running", False):
            return "drink"
        if getattr(self.app, "last_error", False):
            return "dizzy"
        if not self.app.data.get("profiles"):
            return "confused"
        if self._idle() > 60:
            return "sleep"
        return "talk" if self.hover_key == "home_assistant" else "peek"

    def _pop_scale(self):
        """Пружинка при смене позы: 0.86 → 1.06 → 1.0 за ~0.26 с."""
        t = (time.monotonic()-self.pop_start)/0.26
        if t >= 1 or self._reduced_motion():
            return 1.0
        c = 1.70158
        return 0.86+0.14*(1+(c+1)*(t-1)**3+c*(t-1)**2)

    def _hop_offset(self):
        t = (time.monotonic()-self.hop_start)/0.38
        if t >= 1 or self._reduced_motion():
            return 0.0
        return -22*math.sin(math.pi*t)

    def draw_assistant(self, pose, cx, bottom, box_w, box_h, key, command):
        """Рисует спрайт по центру снизу; при смене позы — пружинка."""
        if pose != self.shown_pose:
            self.shown_pose, self.pop_start = pose, time.monotonic()
        scale = self._pop_scale()
        w, h = box_w*scale, box_h*scale
        image = self.assets.photo(f"characters/chibi/{pose}.png", (w, h), True)
        self.photos.append(image)
        y = bottom-image.height()/2+self.guide_offset
        item = self.create_image(cx, y, image=image, tags=("ui", "guide"))
        self.region(key, (cx-image.width()/2, bottom-image.height(), image.width(), image.height()), command)
        return item, image.width(), image.height()

    def poke(self):
        """Щелчок по ассистенту в FAQ: прыжок и случайная реплика."""
        self.last_input = time.monotonic()
        quips = [q for q in ASSISTANT_QUIPS[self.lang] if not self.faq_quip or q[1] != self.faq_quip[1]]
        self.faq_quip = random.choice(quips)
        self.faq_typed = 0
        self.hop_start = time.monotonic()
        self.schedule()

    def speech_bubble(self, text, right, bottom, tail_x, max_w=300):
        """Облачко реплики над ассистентом, хвостик смотрит вниз на него."""
        f = self.font(14)
        lines_w = min(max_w, f.measure(text)+4)
        item = self.text(0, 0, text, 14, INK, "nw", width=lines_w)
        x0, y0, x1, y1 = self.bbox(item)
        bw, bh = x1-x0+28, y1-y0+20
        bx, by = right-bw, bottom-bh
        self.coords(item, bx+14, by+10)
        bubble = self.image(ui_draw.rounded(bw, bh, 12, "#1b1813", "#7a6640", 1, alpha=245), bx, by)
        tail_x = max(bx+18, min(bx+bw-18, tail_x))
        p1, p2, p3 = (tail_x-9, by+bh-1), (tail_x+2, by+bh+11), (tail_x+9, by+bh-1)
        tail = self.create_polygon(*p1, *p2, *p3, fill="#1b1813", outline="", tags="ui")
        self.create_line(*p1, *p2, *p3, fill="#7a6640", tags="ui")
        self.tag_lower(bubble, item)
        self.tag_lower(tail, item)

    def faq_data(self):
        return FAQ_EN if self.lang == "en" else FAQ

    def schedule(self):
        if self.job is None and self.winfo_exists():
            self.job = self.after_idle(self.draw)

    def set_background(self, image):
        self.background_photo = ImageTk.PhotoImage(image)
        self.itemconfigure(self.background_item, image=self.background_photo)
        self.tag_lower(self.background_item)

    def draw(self):
        self.job = None
        if not self.winfo_exists():
            return
        self.delete("ui")
        self.photos, self.regions = [], []
        w, h = self.winfo_width(), self.winfo_height()
        if w < 50:
            return
        self.faq_answer_id = None
        # Мягкие затемнения: под навигацией, над нижней панелью и (на
        # главной) слева под текстом — чтобы надписи читались на любом фоне.
        self.image(ui_draw.gradient(w, 70, "#000000", 150, 0, horizontal=False), 0, NAV_HEIGHT)
        self.image(ui_draw.gradient(w, 90, "#000000", 0, 170, horizontal=False), 0, h-DOCK_HEIGHT-90)
        self.draw_nav(w)
        if self.active == "home":
            self.image(ui_draw.gradient(max(1, w*.6), max(1, h-NAV_HEIGHT-DOCK_HEIGHT), "#000000", 190, 0), 0, NAV_HEIGHT)
            self.draw_home(w, h)
        elif self.active == "faq":
            self.draw_faq(w, h)
        self.draw_dock(w, h)
        self.draw_toast(w)

    def draw_nav(self, w):
        self.create_rectangle(0, 0, w, NAV_HEIGHT, fill="#11110f", outline="", tags="ui")
        self.create_line(0, NAV_HEIGHT-1, w, NAV_HEIGHT-1, fill="#24211b", tags="ui")
        items = [("home", self.tt("nav.home"), self.app.show_home), ("library", self.tt("nav.library"), self.app.show_library),
                 ("mods", self.tt("nav.mods"), self.app.manage_mods), ("saves", self.tt("nav.saves"), self.app.show_saves),
                 ("faq", self.tt("nav.faq"), self.app.show_faq),
                 ("settings", self.tt("nav.settings"), self.app.background_settings)]
        # Шрифт уменьшается, пока вкладки не помещаются между краями окна
        # (справа — переключатель языка, по бокам — стрелки).
        size, pad = 18, 40
        while True:
            widths = [self.font(size, True).measure(label)+pad for _, label, _ in items]
            if sum(widths)+2*48 <= w-2*112 or size <= 13:
                break
            size, pad = size-1, max(24, pad-3)
        x = (w-sum(widths))/2
        nav_left = x-38
        # Стрелки по краям навигации переключают вкладки (как Q/E в игре).
        self._nav_arrow("tab_prev", "navigation/arrow-left.png", "‹", x-38, lambda: self.app.cycle_tab(-1))
        for (key, label, command), width in zip(items, widths):
            self.text(x+width/2, 31, label, size, GOLD if self.active == key or self.hover_key == key else MUTED, "center", bold=True)
            if self.active == key:
                self.asset("navigation/active-glow.png", x+12, 51, width-24, 12, False)
            self.region(key, (x, 10, width, 44), command)
            x += width
            if key != "settings":
                self.asset("navigation/separator.png", x-3, 25, 6, 10)
        self._nav_arrow("tab_next", "navigation/arrow-right.png", "›", x+12, lambda: self.app.cycle_tab(1))
        self._draw_steam_status(nav_left)
        self._draw_lang_switch(w)

    def _nav_arrow(self, key, asset, glyph, x, command):
        hot = key in (self.hover_key, self.focus_key)
        self.asset(asset, x, 21, 26, 22)
        self.text(x+13, 31, glyph, 18, GOLD if hot else MUTED, "center", bold=True)
        self.region(key, (x-4, 17, 34, 30), command)

    def _draw_steam_status(self, nav_left):
        state = getattr(self.app, "steam_state", None)
        if not state:
            return
        items = ((self.tt("nav.steam"), state.get("steam_running")),
                 (self.tt("nav.game"), state.get("base_installed")),
                 (self.tt("nav.dlc"), state.get("erdtree_installed")))
        f = self.font(12, True)
        total = sum(f.measure(label)+22 for label, _ in items)
        if nav_left-28 < total+24:
            return  # узкое окно — не наезжаем на навигацию
        x = 24
        hot = self.hover_key == "steam_status"
        for label, ok in items:
            self.image(ui_draw.circle(8, OK if ok else OFF, glow=OK if ok else None, glow_size=3), x-3, 32-7)
            self.text(x+14, 32, label, 12, (INK if hot else MUTED) if ok else "#6a6253", "w", bold=True)
            x += f.measure(label)+30
        self.region("steam_status", (16, 18, x-16, 28), self.app.refresh_steam_status_now)

    def _draw_lang_switch(self, w):
        sw, sh, sx, sy = 66, 28, w-98, (NAV_HEIGHT-28)/2
        hot = self.hover_key == "lang"
        self.image(ui_draw.pill(sw, sh, "#221f19" if hot else "#17150f", "#8a7550" if hot else "#4a4234"), sx, sy)
        knob_x = sx+sw-sh/2 if self.lang == "en" else sx+sh/2
        d = sh-6
        self.image(ui_draw.circle(d, GOLD if hot else "#e6d7b8", glow="#000000", glow_size=3), knob_x-d/2-3, sy+3-3)
        self.text(sx+sh/2, sy+sh/2, "RU", 10, "#1c1a15" if self.lang == "ru" else MUTED, "center", bold=True)
        self.text(sx+sw-sh/2, sy+sh/2, "EN", 10, "#1c1a15" if self.lang == "en" else MUTED, "center", bold=True)
        self.region("lang", (sx, sy, sw, sh), self.toggle_lang)

    def kind_label(self, profile):
        return self.tt("kind."+profile.get("kind", "other"), self.tt("kind.other"))

    def draw_home(self, w, h):
        center_y = (NAV_HEIGHT+32+h-DOCK_HEIGHT-24)/2
        area_h = h-NAV_HEIGHT-DOCK_HEIGHT
        # Эмблема (дерево с мечом) и название под ней.
        emblem = min(w*.32, area_h*.6, 520)
        ex = w*.655
        ey = NAV_HEIGHT+max(16, (area_h-emblem-96)/2)
        self.asset("branding/launcher-emblem.png", ex-emblem/2, ey, emblem, emblem)
        title_y = ey+emblem+4
        self.text(ex, title_y, "ELDEN RING", int(max(26, min(46, emblem*.1))), GOLD, "n", bold=True)
        self.text(ex, title_y+max(32, min(54, emblem*.115)), "L A U N C H E R", 14, MUTED, "n", bold=True)
        self._draw_home_assistant(w, h)
        left, column = max(32, w*.055), w*.36
        p = self.app._profile()
        count_profiles = len(self.app.data.get("profiles", []))
        label = self.tt("home.profile_title") if p else self.tt("home.library_title")
        self.text(left, center_y-124, label, 14, MUTED, bold=True)
        if p and count_profiles > 1:
            # Быстрое переключение профилей прямо с главной: ‹ 1/3 ›
            index = self.app.listbox.curselection()[0]
            lx = left+self.font(14, True).measure(label)+18
            self.link("profile_prev", "‹", (lx, center_y-130, 22, 26), lambda: self.app.cycle_profile(-1), size=20)
            counter = f"{index+1}/{count_profiles}"
            self.text(lx+28, center_y-124, counter, 14, MUTED, bold=True)
            cx = lx+34+self.font(14, True).measure(counter)
            self.link("profile_next", "›", (cx, center_y-130, 22, 26), lambda: self.app.cycle_profile(1), size=20)
        name = p["name"] if p else self.tt("home.empty_name")
        ready = bool(p and profiles.game_exe(p["path"]).is_file())
        if p:
            # Обложка профиля слева от названия.
            self.image(self.app.profile_cover(p, 66), left, center_y-100)
            tx, tw = left+82, column-82
            self.text(tx, center_y-102, elide(name, self.font(32, True), tw), 32, GOLD, bold=True)
            details = [self.kind_label(p)]
            version = profiles.version_label(p)
            if version:
                details.append(version)
            count = sum(m.get("enabled", True) for m in p.get("mods", []))
            if count:
                details.append(f"{self.tt('home.mods_active')}: {count}")
            self.text(tx, center_y-58, elide(" · ".join(details), self.font(16), tw), 16, TEXT)
            dot_y = center_y-4
            color = OK if ready else WARN
            self.image(ui_draw.circle(10, color, glow=color, glow_size=4), left-4, dot_y-9)
            status = self.tt("home.ready") if ready else self.tt("home.missing")
            if ready and p.get("playtime"):
                status += f"  ·  {self.tt('home.playtime')} {profiles.format_playtime(p['playtime'], self.lang)}"
            if ready and p.get("last_played"):
                status += f"  ·  {self.tt('home.last_played')} {p['last_played']}"
            self.text(left+18, dot_y, elide(status, self.font(16), column-18), 16, INK if ready else WARN, "w")
            self.text(left, center_y+16, elide(p["path"], self.font(14), column, middle=True), 14, DIM)
            # Плашка режима запуска (офлайн/онлайн) — щелчок переключает.
            mode = profiles.launch_mode(p)
            label = self.app.mode_label(p)
            switchable = mode not in ("seamless", "pack")
            hot = switchable and self.hover_key == "launch_mode"
            hint = (" · " + ("switch" if self.lang == "en" else "сменить")) if switchable else ""
            f = self.font(13, True)
            pw = f.measure(label+hint)+40
            dot = {"online": OK, "offline": "#86aee0", "seamless": GOLD, "pack": "#d9925f"}[mode]
            self.image(ui_draw.pill(pw, 26, "#221f19" if hot else "#16140f", "#8a7550" if hot else "#3d3529", 1, alpha=230), left, center_y+44)
            self.image(ui_draw.circle(8, dot, glow=dot, glow_size=3), left+9, center_y+50)
            self.text(left+28, center_y+57, label+hint, 13, GOLD if hot else INK, "w", bold=True)
            if switchable:
                self.region("launch_mode", (left, center_y+44, pw, 26), self.app.toggle_launch_mode)
        else:
            self.text(left, center_y-92, elide(name, self.font(32, True), column), 32, GOLD, bold=True)
            self.text(left, center_y-30, self.tt("home.empty_detail"), 17, TEXT, width=column)
        self.button("play", self.tt("home.play") if ready else self.tt("home.fix_path") if p else self.tt("home.add_game"),
                    (left, center_y+80, min(290, column), 64),
                    self.app.launch if ready else self.app.repair_profile if p else self.app.add_vanilla,
                    not getattr(self.app, "launch_pending", False))
        self.link("profile_actions", self.tt("home.actions") if p else self.tt("home.open_library"),
                  (left, center_y+151, min(290, column), 34), self.app.show_profile_menu if p else self.app.show_library)

    def _draw_home_assistant(self, w, h):
        """Маленький IWaithI выглядывает из-за нижней панели (справа)."""
        area_h = h-NAV_HEIGHT-DOCK_HEIGHT
        box_h = max(96, min(150, area_h*.27))
        box_w = box_h*1.25
        cx, bottom = w-36-box_w/2, h-DOCK_HEIGHT+10
        pose = self.current_pose("home")
        _item, sw, sh = self.draw_assistant(pose, cx, bottom, box_w, box_h, "home_assistant", self.app.show_faq)
        now = time.monotonic()
        text = None
        if self.reaction and now < self.reaction_until and self.reaction_text:
            text = self.reaction_text
        elif self.hover_key == "home_assistant":
            tips = HOME_TIPS[self.lang]
            text = tips[self.tip_index % len(tips)]
        elif pose in CONTEXT_LINES[self.lang]:
            text = CONTEXT_LINES[self.lang][pose]
        if text:
            self.speech_bubble(text, w-20, bottom-sh-8, cx-sw*0.1, max_w=min(300, w*.24))

    def open_faq(self):
        """Вход в FAQ: случайное приветствие, пока вопрос не выбран."""
        self.faq_intro = True
        self.faq_greeting = random.choice(FAQ_GREETINGS_EN if self.lang == "en" else FAQ_GREETINGS)
        self.faq_typed = 0
        self.faq_quip = None
        self.focus_key = None
        self.last_input = time.monotonic()

    def _reduced_motion(self):
        return self.app.data.get("settings", {}).get("reduce_motion", False)

    def draw_faq(self, w, h):
        # Персонаж — СПРАВА, список вопросов — СЛЕВА (по макету из Figma),
        # ниже — диалоговое окно с репликой, как в игре.
        available = h-NAV_HEIGHT-DOCK_HEIGHT
        upper_h = min(350, max(200, available*.5))
        total_w = min(980, w-96)
        reserved_below = 232  # окно диалога: имя + реплика + кнопка
        top = NAV_HEIGHT + max(26, (available-upper_h-reserved_below)/2)
        left = (w-total_w)/2
        char_w = total_w*.38
        faq = self.faq_data()
        self.draw_assistant(self.current_pose("faq"), left+total_w-char_w/2-12, top+upper_h, char_w, upper_h-8,
                            "assistant", self.poke)

        qx, qw = left, total_w*.56
        row_h, gap = 60, 10
        list_h = upper_h
        self.faq_list_bounds = (qx, top, qw, list_h)
        content_h = len(faq)*(row_h+gap)-gap
        self.faq_scroll_max = max(0, content_h-list_h)
        self.faq_scroll_target = min(self.faq_scroll_target, self.faq_scroll_max)
        self.faq_scroll = min(self.faq_scroll, self.faq_scroll_max)

        clip_top, clip_bottom = top, top+list_h
        for index, (question, _, _, _, _, icon) in enumerate(faq):
            y = top+index*(row_h+gap)-self.faq_scroll
            if y < clip_top-2 or y+row_h > clip_bottom+2:
                continue
            key = "faq_"+str(index)
            selected = not self.faq_intro and self.faq_index == index
            hot = selected or self.hover_key == key
            self.asset("dialogs/pill-hover.png" if hot else "dialogs/pill-plain.png", qx, y, qw-10, row_h, False)
            icon_size = row_h*0.66
            icon_x, icon_y = qx+row_h*0.14, y+(row_h-icon_size)/2
            self.asset("dialogs/badge-blank.png", icon_x, icon_y, icon_size, icon_size, False)
            gs = icon_size*0.5
            self.asset(f"dialogs/glyph-{icon}.png", icon_x+(icon_size-gs)/2, icon_y+(icon_size-gs)/2-1, gs, gs,
                       tint=GOLD if hot else "#b9ad94")
            self.text(qx+row_h*0.14+icon_size+18, y+row_h/2, question, 17, GOLD if hot else "#b3a891",
                      "w", width=qw*0.66, bold=True)
            # Номер-подсказка для клавиш 1–9/0.
            if index < 10:
                self.text(qx+qw-34, y+row_h/2, str((index+1) % 10), 12, "#6e6553" if not hot else MUTED, "center", bold=True)
            if selected and qx >= 118:  # в узком окне подсказка «Пробел» не влезает слева
                self.asset("dialogs/indicator.png", qx-118, y+(row_h-64)/2, 108, 64, False)
            self.region(key, (qx, max(clip_top, y), qw-10, min(row_h, clip_bottom-max(clip_top, y))),
                        lambda i=index: self.select_question(i))
        if self.faq_scroll_max > 0:
            track_h = list_h-8
            thumb_h = max(28, track_h*list_h/content_h)
            thumb_y = top+4+(track_h-thumb_h)*(self.faq_scroll/self.faq_scroll_max)
            self.image(ui_draw.pill(4, track_h, "#221f1a"), qx+qw-4, top+4)
            self.image(ui_draw.pill(4, thumb_h, BORDER), qx+qw-4, thumb_y)

        guide = "Launcher guide" if self.lang == "en" else "Проводник лаунчера"
        if self.faq_quip:
            subtitle, answer, action, target = guide, self.faq_quip[1], None, None
        elif self.faq_intro:
            subtitle, answer, action, target = guide, self.faq_greeting, None, None
        else:
            _, subtitle, answer, action, target, _ = faq[self.faq_index]
        self.faq_answer_full = answer
        if self._reduced_motion():
            self.faq_typed = len(answer)

        # Диалоговое окно: полупрозрачная подложка под именем, репликой и кнопкой.
        box_y = top+upper_h+12
        text_w = total_w-120
        answer_y = box_y+80
        answer_id = self.text(w/2, answer_y, answer, 17, TEXT, "n", width=text_w, justify="center")
        bounds = self.bbox(answer_id)
        text_bottom = bounds[3] if bounds else answer_y+72
        action_h = 44 if action else 0
        box_h = (text_bottom-box_y)+(action_h+28 if action else 22)
        panel = self.image(ui_draw.rounded(total_w, box_h, 16, "#0d0c09", "#3d3529", 1, alpha=215), left, box_y)
        self.tag_lower(panel, answer_id)
        self.image(ui_draw.gradient(total_w*.5, 1, GOLD, 0, 150), left, box_y+66)
        self.image(ui_draw.gradient(total_w*.5, 1, GOLD, 150, 0), left+total_w*.5, box_y+66)
        self.text(w/2, box_y+10, app_info.ASSISTANT, 21, GOLD, "n", bold=True)
        self.text(w/2, box_y+50, subtitle.upper(), 11, MUTED, "center", bold=True)
        self.asset("dialogs/ornament-left.png", left+14, box_y+box_h/2-28, 12, 56, False)
        self.asset("dialogs/ornament-left.png", left+total_w-26, box_y+box_h/2-28, 12, 56, False, True)
        # «Печать» реплики: полный текст уже измерен выше, показываем часть.
        if self.faq_typed < len(answer):
            self.itemconfigure(answer_id, text=answer[:self.faq_typed])
            self.region("faq_skip", (left, box_y, total_w, box_h), self._finish_typing)
        self.faq_answer_id = answer_id
        if action:
            self.button("faq_action", action, (w/2-140, text_bottom+14, 280, action_h),
                        lambda target=target: self._faq_action(target), self.faq_typed >= len(answer))

    def _finish_typing(self):
        self.faq_typed = 10**6  # ответ мог ещё не отрисоваться — «до конца» в любом случае
        self.schedule()

    def _faq_action(self, target):
        actions = {"home": self.app.show_home, "library": self.app.show_library, "log": self.app.show_log,
                   "mods": self.app.manage_mods, "settings": self.app.background_settings,
                   "add_game": self.app.add_vanilla, "discord": self.app.copy_discord}
        actions[target]()

    def select_question(self, index):
        if self.faq_intro or self.faq_quip or index != self.faq_index:
            self.faq_typed = 0
        self.faq_intro, self.faq_quip = False, None
        self.last_input = time.monotonic()
        self.faq_index, self.focus_key = index, "faq_"+str(index)
        # Держим выбранный вопрос в видимой части списка.
        if self.faq_list_bounds:
            row = 70
            top, height = index*row, self.faq_list_bounds[3]
            if top < self.faq_scroll_target:
                self.faq_scroll_target = top
            elif top+60 > self.faq_scroll_target+height:
                self.faq_scroll_target = min(self.faq_scroll_max, top+60-height)
        self.schedule()


    def draw_dock(self, w, h):
        y = h-DOCK_HEIGHT
        self.create_rectangle(0, y, w, h, fill="#100f0d", outline="", tags="ui")
        self.create_line(32, y, w-32, y, fill="#393327", tags="ui")
        button_w, picker_w = min(250, w*.23), min(270, w*.25)
        self.button("install", self.app.install_button.text, (32, y+53, button_w, 62),
                    self.app.start_download, self.app.install_button.enabled)
        px = 48+button_w
        self.text(px+12, y+19, self.tt("dock.version_label"), 12, MUTED, bold=True)
        hot = self.app.version_button.enabled and "version" in (self.hover_key, self.focus_key)
        self.image(ui_draw.rounded(picker_w, 44, 8, "#201d16" if hot else "#17150f", "#8a7550" if hot else "#3d3529"), px, y+62)
        version_label = self.tt("dock.current") if versions.install_method(self.app.version.get()) == "steam" else self.app.version.get()
        self.text(px+12, y+84, version_label, 17, TEXT if self.app.version_button.enabled else MUTED, "w", width=picker_w-42, bold=True)
        info = versions.get(self.app.version.get()) or {}
        if info.get("release_date"):
            yy, mm, dd = info["release_date"].split("-")
            self.text(px+12, y+118, f"{dd}.{mm}.{yy}", 12, DIM, "w")
        self.asset("dropdowns/caret.png", px+picker_w-28, y+75, 18, 18)
        self.app.version_button.bounds = (px, y+62, picker_w, 44)
        self.region("version", self.app.version_button.bounds, self.app.version_button.toggle, self.app.version_button.enabled)
        sx, sw = px+picker_w+24, w-(px+picker_w+24)-32
        self.asset("panels/install-background.png", sx, y+23, sw, 102, False)
        self.text(sx+14, y+27, self.app.install_title.text, 17, TEXT, width=sw-30, bold=True)
        busy, progress = getattr(self.app, "operation_running", False), self.app.bar
        bx, by, bw = sx+14, y+69, sw-28
        self.image(ui_draw.pill(bw, 8, "#2b2924"), bx, by)
        if progress.mode == "indeterminate" and busy:
            start = (self.phase % 80)/100
            seg = bw*min(.2, 1-start)
            if seg > 8:
                self.image(ui_draw.pill(seg, 8, GOLD), bx+bw*start, by)
        elif progress.value:
            fill = bw*max(0, min(1, progress.value/100))
            if fill >= 8:
                self.image(ui_draw.pill(fill, 8, GOLD), bx, by)
        self.text(sx+14, y+84, self.app.status.text, 14, GOLD, width=sw-95)
        self.link("log", self.tt("dock.log"), (w-116, y+81, 82, 32), self.app.show_log)
        if self.app.progress_detail.text:
            self.text(sx+14, y+116, elide(self.app.progress_detail.text, self.font(12), sw-95), 12, MUTED)
        if busy:
            self.link("stop", self.tt("dock.stop"), (w-108, y+112, 66, 30), self.app.stop_download)

    def _at(self, x, y):
        for region in reversed(self.regions):
            _, (rx, ry, rw, rh), _ = region
            if rx <= x <= rx+rw and ry <= y <= ry+rh:
                return region

    def _hover(self, key):
        if key != self.hover_key:
            if key == "home_assistant":
                self.tip_index += 1  # каждое наведение — новая подсказка
            self.hover_key = key
            self.configure(cursor="hand2" if key else "")
            self.schedule()

    def _motion(self, e):
        self.last_input = time.monotonic()
        region = self._at(e.x, e.y)
        self._hover(region[0] if region else None)

    def _press(self, e):
        self.app.version_button.close()
        self.focus_set()
        self.keyboard_nav = False
        self.last_input = time.monotonic()
        region = self._at(e.x, e.y)
        self.pressed_key = self.focus_key = region[0] if region else None
        self.schedule()

    def _release(self, e):
        region, pressed = self._at(e.x, e.y), self.pressed_key
        self.pressed_key = None
        if region and region[0] == pressed:
            region[2]()
        self.schedule()

    def _focus_next(self, direction):
        self.keyboard_nav = True
        keys = [r[0] for r in self.regions if r[0] != "faq_skip"]
        if keys:
            i = keys.index(self.focus_key) if self.focus_key in keys else (-1 if direction > 0 else 0)
            self.focus_key = keys[(i+direction) % len(keys)]
            self.schedule()
        return "break"

    def _activate(self, _e=None):
        # Пробел/Enter во время «печати» реплики сначала дописывают её.
        if self.active == "faq" and self.faq_typed < len(self.faq_answer_full):
            self._finish_typing()
            return "break"
        # Подсказка «Пробел» у выбранного вопроса: пробел выполняет его действие.
        if (self.active == "faq" and not self.faq_intro and self.focus_key != "faq_action"
                and (self.focus_key is None or self.focus_key.startswith("faq_"))):
            self._faq_action(self.faq_data()[self.faq_index][4])
            return "break"
        for key, _, action in self.regions:
            if key == self.focus_key:
                action()
                break
        return "break"

    def _key(self, e):
        self.last_input = time.monotonic()
        # 1–9 и 0 — быстрый выбор вопроса в FAQ.
        if self.active == "faq" and e.char and e.char.isdigit():
            index = (int(e.char)-1) % 10
            if index < len(self.faq_data()):
                self.select_question(index)

    def _arrow(self, direction, vertical=False):
        if self.active == "faq" and vertical:
            self.keyboard_nav = True
            start = -1 if self.faq_intro and direction > 0 else self.faq_index
            self.select_question((start+direction) % len(self.faq_data()))
        elif self.active == "home" and not vertical:
            self.app.cycle_profile(direction)
        return "break"

    def _escape(self, _e=None):
        if self.app.version_button.panel:
            return self.app.version_button.close()
        if self.active != "home":
            self.app.show_home()
        return "break"

    def tt(self, key, default=None):
        return t(self.lang, key, default)

    def toggle_lang(self):
        self.lang = "en" if self.lang == "ru" else "ru"
        self.app.data.setdefault("settings", {})["lang"] = self.lang
        profiles.save(self.app.data)
        if self.faq_intro:
            self.faq_greeting = random.choice(FAQ_GREETINGS_EN if self.lang == "en" else FAQ_GREETINGS)
        self.faq_quip, self.faq_typed = None, 10**6
        self.app.on_language_change()
        self.schedule()

    def _wheel(self, event, delta=None):
        if self.active != "faq" or not self.faq_list_bounds:
            return
        x, y, w, h = self.faq_list_bounds
        if not (x <= event.x <= x+w and y <= event.y <= y+h):
            return
        amount = delta if delta is not None else (1 if event.delta > 0 else -1)
        self.faq_scroll_target = max(0, min(self.faq_scroll_max, self.faq_scroll_target - amount*46))
        self.schedule()

    def _tick(self):
        if getattr(self.app, "operation_running", False) and self.app.bar.mode == "indeterminate" and self.app.state() != "iconic":
            self.phase = (self.phase+0.8) % 80
            self.schedule()
        if abs(self.faq_scroll_target - self.faq_scroll) > 0.5:
            self.faq_scroll += (self.faq_scroll_target - self.faq_scroll) * 0.28
            self.schedule()
        elif self.faq_scroll != self.faq_scroll_target:
            self.faq_scroll = self.faq_scroll_target
            self.schedule()
        visible = self.app.state() not in ("iconic", "withdrawn") and not self.app.page_host.winfo_ismapped()
        if self.active == "faq" and visible:
            # Реплика «печатается» без полной перерисовки сцены.
            if self.faq_typed < len(self.faq_answer_full) and self.faq_answer_id:
                self.faq_typed = min(len(self.faq_answer_full), self.faq_typed+3)
                if self.faq_typed >= len(self.faq_answer_full):
                    self.schedule()  # показать кнопку действия
                else:
                    self.itemconfigure(self.faq_answer_id, text=self.faq_answer_full[:self.faq_typed])
        if self.active in ("faq", "home") and visible:
            # Поза сменилась (заснул, реакция закончилась) — перерисовать.
            if self.current_pose(self.active) != self.shown_pose:
                self.schedule()
            # Пружинка при смене позы перерисовывает сцену несколько кадров.
            if time.monotonic()-self.pop_start < 0.3:
                self.schedule()
            # Покачивание (спящий дышит медленнее) и прыжок по щелчку —
            # сдвигаем только изображение ассистента.
            if not self._reduced_motion():
                sleeping = self.shown_pose == "sleep"
                self.guide_phase += 0.02 if sleeping else 0.035
                offset = math.sin(self.guide_phase)*(2 if sleeping else 4)+self._hop_offset()
                self.move("guide", 0, offset-self.guide_offset)
                self.guide_offset = offset
        self.animation_job = self.after(16, self._tick)

    def destroy(self):
        for job in (self.job, self.animation_job):
            if job:
                self.after_cancel(job)
        super().destroy()


def set_active_tab(app, name):
    app.scene.active = name
    app.scene.schedule()


def build_interface(app):
    main = tk.Frame(app, bg=BG)
    main.pack(fill="both", expand=True)
    app.background_main = main
    main.bind("<Configure>", app._on_main_resize)
    app.scene = LauncherScene(app, main)
    app.scene.place(x=0, y=0, relwidth=1, relheight=1)
    app.background_controller = Background(app, app.scene)
    app.install_button = SceneValue(app.scene, app.scene.tt("dock.install"))
    app.version_button = VersionPicker(app.scene, app.version)
    app.install_title = SceneValue(app.scene, app.scene.tt("dock.install_title"))
    app.status = SceneValue(app.scene, app.scene.tt("dock.ready"))
    app.progress_detail = SceneValue(app.scene)
    app.bar = SceneValue(app.scene)
    app.listbox = tk.Listbox(main, exportselection=False)
    app.logbox = tk.Text(main, wrap="word")
    app.page_host = tk.Frame(main, bg=PAGE_BG, highlightthickness=1, highlightbackground=CARD_BORDER)
    app.log_view = None
    app.version.trace_add("write", lambda *_: app.scene.schedule())
    app.bind("<Control-l>", lambda _e: app.show_library())
    app.bind("<F1>", lambda _e: app.show_faq())
    app.bind("<F5>", lambda _e: app.refresh_steam_status_now())
    app.bind("<Control-Tab>", lambda _e: app.cycle_tab(1))
    app.bind("<Control-Shift-Tab>", lambda _e: app.cycle_tab(-1))
    app.bind("<Escape>", lambda _e: app.scene._escape())


def layout_main(app, width, height):
    if hasattr(app, "scene"):
        if app.page_host.winfo_ismapped():
            app.page_host.place(x=32, y=NAV_HEIGHT+20, width=width-64, height=max(200,height-NAV_HEIGHT-DOCK_HEIGHT-40))
        app.version_button.close()
        app.scene.schedule()

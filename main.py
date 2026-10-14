import os
import random
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import app_info
import crash_log
import i18n
import mod_config
import modpacks
import profiles
import saves
import seamless
import steam_download
import steam_checks
import translator
import tray
import ui_draw
import versions
from i18n import tr
from ui_scene import (TABS, CardList, ScrollFrame, TabFrame, TextureButton, ToggleSwitch, Tooltip, build_interface,
                      layout_main, page_section, set_active_tab, slider_row, styled_entry, toggle_row)
from ui_theme import apply_theme, load_embedded_font
from ui_media import assets_dir
from ui_tokens import (NAV_HEIGHT, DOCK_HEIGHT, FONT, PANEL, TEXT, GOLD, MUTED,
                       PAGE_BG, CARD, CARD_BORDER, INK, DIM, OK, WARN, OFF)

KIND_COLORS = {"vanilla": "#8a6a2f", "mods": "#5c4a86", "seamless": "#2f6a5a", "pack": "#7a3b35"}
BACKGROUND_PATTERNS = ("*.jpg", "*.jpeg", "*.png", "*.webp")


def _backgrounds(folder):
    return sorted(path for pattern in BACKGROUND_PATTERNS for path in folder.glob(pattern))


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{app_info.APP_NAME} {app_info.VERSION}")
        self.geometry("1280x820")
        self.minsize(960, 740)
        self.configure(bg="#0b0b0a")
        try:
            self.iconbitmap(default=str(assets_dir() / "icon.ico"))
        except tk.TclError:
            pass
        load_embedded_font(assets_dir())
        apply_theme(self)
        crash_log.install(self)
        self.operation_running = False
        self.copy_running = False
        self.launch_pending = False
        self.background_cycle_job = None
        self.steam_status_job = None
        self.steam_state = None
        self.last_error = False
        self.playtime_thread = None
        self.game_running = False
        self.restore_after_game = False
        self.stop = threading.Event()
        self.data = profiles.load()
        i18n.set_lang(self._settings().get("lang", "ru"))
        self._restore_geometry()
        self.screenshot_paths = []
        self.default_background_paths = _backgrounds(assets_dir() / "default_backgrounds")
        self.background_index = 0
        self.background_photo = None
        self.background_main = None
        self.background_ready = False
        self.current_background_source = None
        self.background_resize_job = None
        self.selected = tk.StringVar()
        self.version = tk.StringVar(value=(versions.names() or [""])[0])
        self.download_path = tk.StringVar()
        self.tray = tray.TrayIcon(self, assets_dir() / "icon.png", app_info.APP_NAME)
        build_interface(self)
        self.refresh()
        self._select_saved_profile()
        self.version.trace_add("write", lambda *_: self._on_version_change())
        self._on_version_change()
        self.protocol("WM_DELETE_WINDOW", self.request_close)
        self.bind("<Unmap>", self._on_unmap)
        self.after(500, self.refresh_steam_background)
        self.after(900, self.refresh_steam_status)
        self.after(1500, self._restore_loaders_on_start)

    def _restore_loaders_on_start(self):
        # Лаунчер закрыли во время игры или он упал — возвращаем отключённые загрузчики.
        if self._settings().get("renamed_loaders") and not saves.game_running():
            self._restore_loaders()

    # ── общие помощники ────────────────────────────────────────────────

    def tt(self, key, default=None):
        return self.scene.tt(key, default)

    def _settings(self):
        return self.data.setdefault("settings", {})

    def _restore_geometry(self):
        geometry = self._settings().get("window_geometry", "")
        match = re.fullmatch(r"(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)", geometry)
        if match:
            w, h, x, y = (int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4)))
            # Не восстанавливаем окно за пределами экрана (например, после
            # отключения второго монитора).
            if -w // 2 < x < self.winfo_screenwidth() - 120 and 0 <= y < self.winfo_screenheight() - 120:
                self.geometry(f"{max(960, w)}x{max(740, h)}{match.group(3)}{match.group(4)}")
        if self._settings().get("window_zoomed"):
            self.after(50, lambda: self.state("zoomed"))

    def _save_geometry(self):
        settings = self._settings()
        if self.state() in ("normal", "zoomed"):
            settings["window_zoomed"] = self.state() == "zoomed"
        if self.state() == "normal":
            settings["window_geometry"] = self.geometry()
        try:
            profiles.save(self.data)
        except OSError:
            pass

    def refresh(self):
        selected = self.listbox.curselection()
        selected_index = selected[0] if selected else 0
        self.listbox.delete(0, "end")
        for p in self.data["profiles"]: self.listbox.insert("end", f"{p['name']}  [{p['kind']}] — {p['path']}")
        if self.data["profiles"]:
            self.listbox.selection_set(min(selected_index, len(self.data["profiles"]) - 1))
        if hasattr(self,"scene"):
            self.scene.schedule()

    def select_profile(self, index, save=True):
        if not (0 <= index < len(self.data["profiles"])):
            return
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        if save:
            self._settings()["selected_profile"] = self.data["profiles"][index]["name"]
            profiles.save(self.data)
        self.scene.schedule()

    def _select_by_name(self, name):
        for index, profile in enumerate(self.data["profiles"]):
            if profile["name"] == name:
                self.select_profile(index)
                return

    def _select_saved_profile(self):
        name = self._settings().get("selected_profile")
        for index, profile in enumerate(self.data["profiles"]):
            if profile["name"] == name:
                self.select_profile(index, save=False)
                return

    def _find_profile(self, name):
        return next((p for p in self.data["profiles"] if p["name"] == name), None)

    def cycle_profile(self, direction):
        count = len(self.data["profiles"])
        if count < 2:
            return
        current = self.listbox.curselection()
        self.select_profile(((current[0] if current else 0) + direction) % count)

    def cycle_tab(self, direction):
        actions = {"home": self.show_home, "library": self.show_library, "mods": self.manage_mods,
                   "saves": self.show_saves, "faq": self.show_faq, "settings": self.background_settings}
        current = self.scene.active if self.scene.active in TABS else "home"
        actions[TABS[(TABS.index(current) + direction) % len(TABS)]]()
        return "break"

    def on_language_change(self):
        i18n.set_lang(self.scene.lang)
        if not self.operation_running and not self.copy_running:
            self.status.configure(text=self.tt("dock.ready"))
            self.progress_detail.configure(text="")
        self._update_install_mode()
        if self.tray.visible:
            self._show_tray()
        # Открытая вкладка перерисовывается, чтобы сменить язык.
        reopen = {"library": self.show_library, "mods": self.manage_mods, "saves": self.show_saves,
                  "settings": self.background_settings, "log": self.show_log}.get(self.scene.active)
        if reopen and self.page_host.winfo_ismapped():
            reopen()

    def _confirm_new_name(self, name, parent=None):
        if not profiles.exists(self.data, name):
            return True
        return messagebox.askyesno(tr("Профиль уже есть"),
                                   tr("Профиль «{name}» уже существует. Заменить запись?\n\nФайлы игры на диске не удаляются.").format(name=name),
                                   parent=parent or self)

    def open_url(self, url):
        webbrowser.open(url)

    # ── Steam-статус (в фоне, чтобы не подвешивать интерфейс) ─────────

    def refresh_steam_status(self):
        """Проверка Steam идёт в отдельном потоке: tasklist и обход дисков
        занимают сотни миллисекунд и раньше подвешивали интерфейс."""
        self.steam_status_job = None
        paths = [p["path"] for p in self.data.get("profiles", [])]

        def work():
            try:
                checks = steam_checks.status(paths)
            except Exception:
                checks = None
            try:
                running = saves.game_running()  # игра могла быть запущена и не из лаунчера
            except Exception:
                running = False

            def apply():
                if not (self.playtime_thread and self.playtime_thread.is_alive()):
                    self.game_running = running
                if checks is not None:
                    self.steam_state = checks
                    self.scene.schedule()
                if self.steam_status_job is None:
                    self.steam_status_job = self.after(20000, self.refresh_steam_status)
            try:
                self.after(0, apply)
            except RuntimeError:
                pass  # окно уже закрыто
        threading.Thread(target=work, daemon=True).start()

    def refresh_steam_status_now(self):
        if self.steam_status_job:
            self.after_cancel(self.steam_status_job)
            self.steam_status_job = None
        self.refresh_steam_status()

    # ── трей ───────────────────────────────────────────────────────────

    def _tray_enabled(self):
        return tray.available() and self._settings().get("use_tray", True)

    def _show_tray(self):
        profile = self._profile()
        items = [(tr("Открыть лаунчер"), self.restore_from_tray, True)]
        if profile and profiles.game_exe(profile["path"]).is_file():
            items.append((tr("Играть: {name}").format(name=profile["name"]), self.launch, False))
        items.append((tr("Выход"), self.quit_from_tray, False))
        self.tray.show(items)

    def hide_to_tray(self):
        if not self._tray_enabled():
            self.iconify()
            return
        self.withdraw()
        self._show_tray()

    def _on_unmap(self, event):
        # Сворачивание окна кнопкой «_» уводит лаунчер в трей, если это включено.
        if event.widget is self and self.state() == "iconic" and self._tray_enabled():
            self.after(10, self.hide_to_tray)

    def restore_from_tray(self):
        self.tray.hide()
        self.deiconify()
        self.state("zoomed" if self._settings().get("window_zoomed") else "normal")
        self.lift()
        self.focus_force()

    def quit_from_tray(self):
        self.restore_from_tray()
        self.request_close()

    # ── фон ────────────────────────────────────────────────────────────

    def _apply_panel_opacity(self, value=None):
        # Never fade text or child HWNDs: transitions belong to the background.
        self.scene.schedule()

    def _on_main_resize(self, event):
        if event.widget is not self.background_main:
            return
        self._layout_main(event.width, event.height)
        if self.background_resize_job:
            self.after_cancel(self.background_resize_job)
        self.background_resize_job = self.after(350, self._resize_background)

    def _layout_main(self, width: int, height: int):
        layout_main(self, width, height)

    def _resize_background(self):
        self.background_resize_job = None
        if self.current_background_source:
            self._set_background_source(self.current_background_source, animated=False)

    def _set_background_source(self, source, animated=True):
        self.current_background_source = source
        self.background_controller.request(source, animated)

    def refresh_steam_background(self):
        if self.background_cycle_job:
            self.after_cancel(self.background_cycle_job)
            self.background_cycle_job = None
        self.screenshot_paths = profiles.steam_screenshot_paths()
        random.shuffle(self.screenshot_paths)
        self.default_background_paths = _backgrounds(assets_dir() / "default_backgrounds")
        self.background_index = 0
        self._show_next_background()

    def _show_next_background(self):
        self.background_cycle_job = None
        use_steam = self._settings().get("steam_background_enabled", True)
        paths = self.screenshot_paths if use_steam and self.screenshot_paths else self.default_background_paths
        if paths and self.state() not in ("iconic", "withdrawn") and not self.game_running:
            self._set_background_source(paths[self.background_index % len(paths)], animated=True)
            self.background_index += 1
        interval = max(5, int(self._settings().get("background_interval_seconds", 15)))
        self.background_cycle_job = self.after(interval*1000, self._show_next_background)

    # ── вкладки ────────────────────────────────────────────────────────

    def _open_tab(self, title, subtitle=None):
        self.version_button.close()
        self.log_view = None
        for child in self.page_host.winfo_children():
            child.destroy()
        self.page_host.place(x=32, y=NAV_HEIGHT+20, width=self.winfo_width()-64,
                             height=max(200,self.winfo_height()-NAV_HEIGHT-DOCK_HEIGHT-40))
        self.page_host.lift()
        page = TabFrame(self.page_host, bg=PAGE_BG)
        page.pack(fill="both", expand=True)
        header = tk.Frame(page, bg=PAGE_BG)
        header.pack(fill="x", padx=20, pady=(14, 10))
        tk.Label(header, text=title.upper(), bg=PAGE_BG, fg=GOLD,
                 font=(FONT, -24, "bold")).pack(side="left", anchor="w")
        if subtitle:
            tk.Label(header, text=subtitle, bg=PAGE_BG, fg=DIM,
                     font=(FONT, -14)).pack(side="left", anchor="s", padx=(14, 0), pady=(0, 4))
        page.header = header
        self.scene.schedule()
        return page

    def _close_tab(self):
        self.version_button.close()
        self.log_view = None
        for child in self.page_host.winfo_children():
            child.destroy()
        self.page_host.place_forget()
        set_active_tab(self, "home")
        self.scene.focus_set()

    def _button(self, parent, text, command, width=170, height=42, small=True, tooltip=None, enabled=True):
        button = TextureButton(parent, self.scene.assets, text, command, width=width, height=height, small=small,
                               tooltip=tooltip)
        button.set_enabled(enabled)
        return button

    def background_settings(self):
        set_active_tab(self, "settings")
        window = self._open_tab(self.tt("page.settings"))
        settings = self._settings()

        # Содержимое прокручивается, если не влезает (минимальное окно 960×740).
        scroll = ScrollFrame(window, PAGE_BG)
        scroll.pack(fill="both", expand=True, pady=(0, 6))
        columns = tk.Frame(scroll.inner, bg=PAGE_BG)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(0, weight=1, uniform="col")
        columns.columnconfigure(1, weight=1, uniform="col")
        left_col = tk.Frame(columns, bg=PAGE_BG)
        right_col = tk.Frame(columns, bg=PAGE_BG)
        left_col.grid(row=0, column=0, sticky="nsew")
        right_col.grid(row=0, column=1, sticky="nsew")

        def wrapped(parent, text, fg=DIM, size=-13, pady=(6, 0), bold=False):
            label = tk.Label(parent, text=text, bg=CARD, fg=fg, font=(FONT, size, "bold") if bold else (FONT, size),
                             justify="left", anchor="w")
            label.pack(anchor="w", fill="x", pady=pady)
            label.bind("<Configure>", lambda e: label.configure(wraplength=max(200, e.width-4)))
            return label

        skip_startup = tk.BooleanVar(value=settings.get("skip_startup_screen", False))
        minimize = tk.BooleanVar(value=settings.get("minimize_on_launch", False))
        use_tray = tk.BooleanVar(value=settings.get("use_tray", True) and tray.available())
        launch = page_section(left_col, tr("Запуск"), padx=(20, 7))
        toggle_row(launch, tr("Не показывать стартовый экран"), skip_startup,
                   tr("Лаунчер откроется сразу, без заставки с логотипом."))
        toggle_row(launch, tr("Сворачивать лаунчер при запуске игры"), minimize,
                   tr("После выхода из игры окно вернётся само."))
        toggle_row(launch, tr("Сворачивать в трей"), use_tray,
                   tr("Значок у часов вместо панели задач: открыть, играть, выйти.") if tray.available()
                   else tr("Недоступно: в сборке нет модуля pystray."))

        translate = tk.BooleanVar(value=settings.get("translate_configs", True))
        mods_card = page_section(left_col, tr("Моды"), padx=(20, 7))
        toggle_row(mods_card, tr("Переводить настройки модов на русский"), translate,
                   tr("Названия и подсказки из ini-файлов модов. Частые термины — встроенным словарём, остальное — онлайн-переводчиком (Google), с кэшем. Отправляется только текст настроек."))

        about = page_section(left_col, tr("О программе"), padx=(20, 7))
        wrapped(about, tr("{name} · версия {version}").format(name=app_info.APP_NAME, version=app_info.VERSION),
                fg=INK, size=-15, bold=True, pady=(4, 0))
        wrapped(about, tr(app_info.DISCLAIMER))
        wrapped(about, tr(app_info.CREDITS))
        contact = tk.Frame(about, bg=CARD)
        contact.pack(fill="x", pady=(12, 0))
        tk.Label(contact, text=tr("Discord автора:"), bg=CARD, fg=INK, font=(FONT, -14)).pack(side="left")
        tk.Label(contact, text=app_info.DISCORD, bg=CARD, fg=GOLD, font=(FONT, -15, "bold")).pack(side="left", padx=(6, 0))
        buttons_row = tk.Frame(about, bg=CARD)
        buttons_row.pack(fill="x", pady=(10, 0))
        self._button(buttons_row, tr("Скопировать тег"), self.copy_discord, 160, 40,
                     tooltip=tr("Скопировать Discord-тег автора в буфер обмена")).pack(side="left", padx=(0, 8))
        self._button(buttons_row, tr("Папка данных"), self.open_data_folder, 140, 40,
                     tooltip=str(profiles.data_dir())).pack(side="left")

        state = tk.BooleanVar(value=settings.get("steam_background_enabled", True))
        reduced = tk.BooleanVar(value=settings.get("reduce_motion", False))
        darkness = tk.IntVar(value=int(settings.get("background_darkness", 72)))
        interval = tk.IntVar(value=int(settings.get("background_interval_seconds", 15)))
        bg = page_section(right_col, tr("Фон"), padx=(7, 20))
        toggle_row(bg, tr("Скриншоты Elden Ring из Steam"), state,
                   tr("Если выключить или скриншотов нет — встроенные фоны лаунчера."))
        toggle_row(bg, tr("Уменьшить движение"), reduced, tr("Без плавных переходов и анимаций ассистента."))
        slider_row(bg, darkness, 25, 90, tr("Затемнение фона"), lambda v: f"{int(float(v))}%")
        slider_row(bg, interval, 5, 90, tr("Смена фона"), lambda v: tr("{n} сек").format(n=int(float(v))))
        footer = tk.Frame(bg, bg=CARD)
        footer.pack(fill="x", pady=(16, 0))
        count = tk.Label(footer, bg=CARD, fg=DIM, font=(FONT, -12), anchor="w", justify="left")
        count.pack(side="left", fill="x", expand=True)

        def update_count():
            count.configure(text=tr("Скриншотов в Steam: {steam}\nВстроенных фонов: {builtin}").format(
                steam=len(self.screenshot_paths), builtin=len(self.default_background_paths)))
        update_count()

        def rescan():
            self.screenshot_paths = profiles.steam_screenshot_paths()
            self.background_index = 0
            update_count()
            self.scene.toast(tr("Найдено скриншотов: {n}").format(n=len(self.screenshot_paths)))
        self._button(footer, tr("Пересканировать"), rescan, 170, 40).pack(side="right")

        def apply():
            settings["skip_startup_screen"] = skip_startup.get()
            settings["minimize_on_launch"] = minimize.get()
            settings["use_tray"] = use_tray.get()
            settings["translate_configs"] = translate.get()
            settings["steam_background_enabled"] = state.get()
            settings["reduce_motion"] = reduced.get()
            settings["background_darkness"] = int(darkness.get())
            settings["background_interval_seconds"] = int(interval.get())
            profiles.save(self.data)
            self._apply_panel_opacity()
            self.refresh_steam_background()
            self._close_tab()
            self.scene.toast(tr("Настройки сохранены"))

        # Кнопки в заголовке: всегда видны, даже в минимальном окне 960×740.
        self._button(window.header, tr("Применить"), apply, 160, 42).pack(side="right")
        self._button(window.header, tr("Отмена"), self._close_tab, 120, 42,
                     tooltip=tr("Закрыть без сохранения (Esc)")).pack(side="right", padx=(0, 8))

    def open_data_folder(self):
        os.startfile(profiles.data_dir())

    def show_home(self):
        """Возвращает к главной странице без создания нового окна."""
        self._close_tab()

    def profile_cover(self, profile, size):
        letter = (profile["name"].strip()[:1] or "?").upper()
        return ui_draw.cover(profile.get("cover"), size, letter, KIND_COLORS.get(profile.get("kind"), "#6b5a3a"))

    def profile_meta(self, profile):
        """Короткая строка для карточки: режим · версия игры · время в игре · моды."""
        parts = [{"online": tr("онлайн"), "offline": tr("офлайн"), "seamless": "co-op",
                  "pack": tr("свой загрузчик")}[profiles.launch_mode(profile)]]
        version = profiles.version_label(profile)
        if version:
            parts.append(version)
        if profile.get("playtime"):
            parts.append(profiles.format_playtime(profile["playtime"], i18n.LANG))
        mods = sum(m.get("enabled", True) for m in profile.get("mods", []))
        if mods:
            parts.append(tr("модов: {n}").format(n=mods))
        return " · ".join(parts)

    def _profile_row(self, profile):
        ready = profiles.game_exe(profile["path"]).is_file()
        return {
            "title": profile["name"],
            "subtitle": profile["path"],
            "badge": self.scene.kind_label(profile).upper(),
            "status": OK if ready else WARN,
            "meta": (self.profile_meta(profile) or tr("готов")) if ready else tr("нет eldenring.exe"),
            "meta_color": DIM if ready else WARN,
            "cover": self.profile_cover(profile, 44),
        }

    def show_library(self):
        set_active_tab(self, "library")
        count = len(self.data["profiles"])
        window = self._open_tab(self.tt("page.library"),
                                tr("Профилей: {n} · двойной щелчок — выбрать, ПКМ — меню").format(n=count) if count
                                else tr("Отдельные установки и мод-профили"))

        def select(index):
            self.select_profile(index)

        def choose(index=None):
            if index is not None:
                self.select_profile(index)
            if self._profile():
                self.show_home()

        def mutate(command):
            command()
            if self.scene.active == "library":
                self.show_library()

        actions = tk.Frame(window, bg=PAGE_BG)
        actions.pack(fill="x", side="bottom", padx=20, pady=(4, 16))
        cards = CardList(window, on_select=select, on_activate=choose, on_context=self.show_profile_menu,
                         empty_text=tr("Профилей пока нет.\nНажмите «Добавить игру» — лаунчер сам поищет установку в Steam."),
                         empty_image=self.scene.sprite_photo("confused", 150))
        cards.pack(fill="both", expand=True, padx=20, pady=(0, 8))
        self.library_list = cards
        selected = self.listbox.curselection()
        cards.set_rows([self._profile_row(p) for p in self.data["profiles"]], selected[0] if selected else None)
        cards.focus_set()
        has_profile = bool(self.data["profiles"])
        for text, command, tip, enabled in (
            (tr("Играть"), lambda: (choose(), self.launch()), tr("Выбрать профиль и запустить игру"), has_profile),
            (tr("Добавить игру"), lambda: mutate(self.add_vanilla), tr("Найти Elden Ring в Steam или указать папку вручную"), True),
            (tr("Модпак"), lambda: self._modpack_source_menu(mutate), tr("Импорт распакованного модпака (Reforged, Convergence…) или профиль прямо из файла .me3"), has_profile),
            (tr("Создать копию"), lambda: mutate(self.create_mod), tr("Скопировать выбранную установку в отдельный мод-профиль"), has_profile),
            (tr("Действия"), self.show_profile_menu, tr("Обложка, папка, моды, путь, переименование, удаление"), has_profile),
        ):
            self._button(actions, text, command, 156, 50, small=False, tooltip=tip, enabled=enabled).pack(side="left", padx=(0, 8))

    def _modpack_source_menu(self, mutate):
        menu = tk.Menu(self, tearoff=False, bg=PANEL, fg=TEXT, activebackground="#443b2d", activeforeground=GOLD, font=(FONT, -16))
        menu.add_command(label=tr("Папка модпака… (лаунчер сам найдёт .me3 или загрузчик)"), command=lambda: mutate(self.import_modpack))
        menu.add_command(label=tr("Файл .me3… (запуск напрямую по нему)"), command=lambda: mutate(self.import_me3_file))
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def show_faq(self):
        self._close_tab()
        self.scene.open_faq()
        set_active_tab(self, "faq")

    def copy_discord(self):
        self.clipboard_clear()
        self.clipboard_append(app_info.DISCORD)
        self.scene.toast(tr("Discord-тег «{tag}» скопирован").format(tag=app_info.DISCORD))
        self.scene.react("smug")

    def _profile(self):
        i = self.listbox.curselection()
        return self.data["profiles"][i[0]] if i else None

    def _known_version(self, game_dir):
        """Версия игры, если папку скачал сам лаунчер (или она внутри такой папки)."""
        game_dir = Path(game_dir).resolve()
        for dest, version in self.data.get("downloads", {}).items():
            dest = Path(dest)
            if game_dir == dest or dest in game_dir.parents:
                return version
        return None

    def add_vanilla(self):
        known = {str(Path(p["path"]).resolve()).lower() for p in self.data["profiles"]}
        try:
            found = [path for path in steam_checks.find_game_dirs() if str(path).lower() not in known]
        except OSError:
            found = []
        path, from_steam = None, False
        if found:
            answer = messagebox.askyesnocancel(
                tr("Найдена установка"),
                tr("Elden Ring найден в Steam:\n{path}\n\nДобавить его? «Нет» — выбрать папку вручную.").format(path=found[0]),
                parent=self,
            )
            if answer is None:
                return
            if answer:
                path, from_steam = str(found[0]), True
        if not path:
            path = filedialog.askdirectory(title=tr("Выберите папку Game с eldenring.exe"), parent=self)
            if not path:
                return
        if not profiles.game_exe(path).is_file():
            return messagebox.showerror(tr("Не найдена игра"), tr("В выбранной папке нет eldenring.exe."), parent=self)
        game_dir = profiles.game_exe(path).parent
        version = tr("Актуальная (Steam)") if from_steam else self._known_version(game_dir)
        base = tr("Ваниль")
        default = f"{base} {version}" if version and not from_steam else base
        if profiles.exists(self.data, default):
            default = f"{default} (2)"
        name = simpledialog.askstring(tr("Название профиля"), tr("Например: Ваниль 1.16"), initialvalue=default, parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        if not self._confirm_new_name(name):
            return
        profiles.add(self.data, name, str(game_dir), "vanilla")
        if version:
            profiles.set_profile_option(self.data, name, "game_version", version)
        # Установка из Steam — онлайн, скачанные старые версии и копии — офлайн.
        profiles.set_profile_option(self.data, name, "launch_mode", "online" if from_steam else "offline")
        self.refresh()
        self._select_by_name(name)
        self.refresh_steam_status_now()
        self.scene.react("smug")

    def create_mod(self):
        if self.operation_running or self.copy_running:
            return
        source = self._profile()
        if not source: return messagebox.showinfo(tr("Выберите ваниль"), tr("Сначала выберите ванильный профиль."), parent=self)
        name = simpledialog.askstring(tr("Название"), tr("Название мод-профиля"), initialvalue=f"{source['name']} · {tr('моды')}", parent=self)
        if not name or not name.strip(): return
        name = name.strip()
        if not self._confirm_new_name(name):
            return
        target = filedialog.askdirectory(title=tr("Выберите папку, в которой будет создана копия"), parent=self)
        if not target: return
        target = str(Path(target) / profiles.safe_folder_name(name))
        game_dir = profiles.game_exe(source["path"]).parent
        problem = profiles.clone_check(str(game_dir), target)
        if problem:
            self.log(tr("Копия для модов: {error}").format(error=tr(problem)))
            return messagebox.showerror(tr("Нельзя создать профиль"), tr(problem), parent=self)
        self.copy_running = True
        self.install_button.configure(state="disabled")
        self.status.configure(text=tr("Считаю размер игры…"))
        self.bar.configure(mode="indeterminate", value=0)
        self.bar.start()
        self.progress_detail.configure(text=tr("Лаунчер остаётся доступен; копирование может занять несколько минут."))
        self.log(tr("Копия для модов: {src} → {dst}").format(src=game_dir, dst=target))
        self.scene.toast(tr("Создаю копию игры для модов — прогресс внизу"), 4)
        threading.Thread(target=self._create_mod_worker, args=(source, target, name), daemon=True).start()

    def _create_mod_worker(self, source, target_path, name):
        error = None
        copying = False
        game_dir = str(profiles.game_exe(source["path"]).parent)
        try:
            files = profiles.game_files(game_dir)
            need = sum(size for _path, size in files)
            free = shutil.disk_usage(Path(target_path).parent).free
            self.log(tr("Размер игры: {need:.1f} ГБ, свободно: {free:.1f} ГБ").format(need=need/2**30, free=free/2**30))
            if free < need * 1.02:
                answer = threading.Event()
                result = {}
                def ask():
                    self.bar.stop()
                    result["ok"] = messagebox.askyesno(
                        tr("Мало места"), tr("Для копии нужно около {need:.1f} ГБ, а свободно {free:.1f} ГБ.\n\nВсё равно продолжить?").format(
                            need=need/2**30, free=free/2**30), parent=self)
                    answer.set()
                self.after(0, ask)
                answer.wait()
                if not result.get("ok"):
                    raise ValueError(tr("Копирование отменено: не хватает места на диске."))
            started = time.monotonic()
            last = {"t": 0.0, "pct": -10}
            def progress(done, total, file):
                now = time.monotonic()
                if now - last["t"] < 0.25 and done < total:
                    return
                last["t"] = now
                pct = done * 100 / total
                if pct - last["pct"] >= 10:
                    last["pct"] = pct - pct % 10
                    self.log(tr("Копирование: {pct:.0f}%").format(pct=pct))
                speed = done / max(0.1, now - started)
                left = (total - done) / speed if speed else 0
                detail = tr("{done:.1f} из {total:.1f} ГБ · осталось ~{min} мин · {file}").format(
                    done=done/2**30, total=total/2**30, min=max(1, round(left / 60)), file=file)
                def show():
                    self.bar.stop()
                    self.bar.configure(mode="determinate", value=pct)
                    self.status.configure(text=tr("Копия для модов: {pct:.1f}%").format(pct=pct))
                    self.progress_detail.configure(text=detail)
                self.after(0, show)
            copying = True
            profiles.clone_vanilla(game_dir, target_path, progress, files)
        except (ValueError, OSError) as exc:
            error = str(exc)
            if copying and Path(target_path).is_dir():
                # Папка была пустой или новой (проверено clone_check) — убираем недокопированное.
                shutil.rmtree(target_path, ignore_errors=True)
            if isinstance(exc, PermissionError):
                error = tr("Нет прав на запись в выбранную папку:\n{error}\n\nВыберите папку на другом диске (не Program Files) или запустите лаунчер от имени администратора.").format(error=exc)
        self.log(tr("Копия для модов: ошибка — {error}").format(error=error) if error
                 else tr("Копия для модов готова: {path}").format(path=target_path))
        def complete():
            self.copy_running = False
            self.bar.stop()
            self.bar.configure(mode="determinate", value=0 if error else 100)
            try:
                if error:
                    raise ValueError(error)
                profiles.add(self.data, name, target_path, "mods")
                profiles.set_profile_option(self.data, name, "launch_mode", "offline")
                if source.get("game_version"):
                    profiles.set_profile_option(self.data, name, "game_version", source["game_version"])
                self.refresh()
                self._select_by_name(name)
                self.status.configure(text=tr("Мод-профиль создан"))
                self.progress_detail.configure(text=tr("Папка: {path}").format(path=target_path))
                if self.scene.active == "library":
                    self.show_library()
            except (ValueError, OSError) as exc:
                self.status.configure(text=tr("Ошибка создания профиля"))
                self.progress_detail.configure(text=tr(str(exc)).splitlines()[0])
                messagebox.showerror(tr("Нельзя создать профиль"), tr(str(exc)), parent=self)
            finally:
                self._update_install_mode()
        self.after(0, complete)

    def rename_profile(self):
        p = self._profile()
        if not p:
            return
        name = simpledialog.askstring(tr("Переименовать"), tr("Новое название профиля"), initialvalue=p["name"], parent=self)
        if not name or not name.strip() or name.strip() == p["name"]:
            return
        name = name.strip()
        if profiles.exists(self.data, name):
            return messagebox.showerror(tr("Имя занято"), tr("Профиль «{name}» уже существует.").format(name=name), parent=self)
        p["name"] = name
        self._settings()["selected_profile"] = name
        profiles.save(self.data)
        self.refresh()
        self._refresh_open_page()

    def change_cover(self):
        p = self._profile()
        if not p:
            return
        path = filedialog.askopenfilename(parent=self, title=tr("Картинка для обложки профиля"),
                                          filetypes=[(tr("Изображения"), "*.png *.jpg *.jpeg *.webp *.bmp")])
        if not path:
            return
        try:
            profiles.set_cover(self.data, p, path)
        except OSError as exc:
            return messagebox.showerror(tr("Не удалось открыть картинку"), str(exc), parent=self)
        self.scene.schedule()
        self._refresh_open_page()

    def remove_cover(self):
        p = self._profile()
        if p and p.pop("cover", None):
            profiles.save(self.data)
            self.scene.schedule()
            self._refresh_open_page()

    def _refresh_open_page(self):
        if not self.page_host.winfo_ismapped():
            return
        reopen = {"library": self.show_library, "mods": self.manage_mods}.get(self.scene.active)
        if reopen:
            reopen()

    def delete_profile(self):
        p = self._profile()
        if p and messagebox.askyesno(tr("Удалить запись"), tr("Удалить профиль «{name}» из списка?\n\nФайлы игры останутся на диске.").format(name=p["name"]), parent=self):
            profiles.remove(self.data, p["name"]); self.refresh()
            self._refresh_open_page()

    def open_folder(self):
        p = self._profile()
        if not p:
            return
        if not Path(p["path"]).is_dir():
            return messagebox.showerror(tr("Папка недоступна"), tr("Папка не найдена:\n{path}").format(path=p["path"]), parent=self)
        os.startfile(p["path"])

    # ── моды и Seamless Co-op ──────────────────────────────────────────

    def manage_mods(self):
        set_active_tab(self, "mods")
        profile = self._profile()
        if not profile:
            window = self._open_tab(self.tt("page.mods"))
            empty = tk.Frame(window, bg=PAGE_BG)
            empty.pack(expand=True)
            photo = self.scene.sprite_photo("confused", 160)
            tk.Label(empty, image=photo, bg=PAGE_BG).pack()
            tk.Label(empty, text=tr("Сначала выберите или создайте профиль в библиотеке."),
                     bg=PAGE_BG, fg=INK, font=(FONT, -18)).pack(pady=(10, 18))
            self._button(empty, tr("Открыть библиотеку"), self.show_library, 220, 48, small=False).pack()
            return
        if profile.get("kind") == "pack" and profile.get("pack_type") == "loader":
            return self._pack_page(profile)
        self._ensure_pack_entry(profile)
        window = self._open_tab(self.tt("page.mods"), tr("{name} · моды загружаются сверху вниз через Mod Engine 3").format(name=profile["name"]))
        coop_on = bool(profiles.seamless_mod(profile, enabled_only=True))

        # Строки списка: сами моды и — под модпаком — его DLL и пакеты по профилю
        # автора. Каждую часть модпака можно выключить и настроить отдельно.
        row_map = []

        def mod_row(index, item):
            enabled = item.get("enabled", True)
            exists = Path(item["path"]).exists()
            pack = profiles.is_me3_pack(item)
            if pack and exists:
                parts = profiles.pack_parts(item, coop_on)
                active = sum(1 for part in parts if part["enabled"] and part["exists"])
                meta = tr("включено частей: {on} из {total}").format(on=active, total=len(parts))
            else:
                meta = (tr("включён") if enabled else tr("выключен")) if exists else tr("не найден")
            return {
                "title": f"{index+1}.  {item['name']}",
                "subtitle": item["path"],
                "badge": "CO-OP" if profiles.is_seamless(item) else tr("МОДПАК") if pack else "DLL" if item.get("kind") == "native" else tr("ПАКЕТ"),
                "status": (OK if enabled else OFF) if exists else WARN,
                "meta": meta if enabled or not exists else tr("выключен"),
                "meta_color": WARN if not exists else DIM,
                "dim": not enabled,
            }

        def part_row(item, part):
            on = part["enabled"] and item.get("enabled", True)
            path = Path(part["path"])
            try:
                shown = str(path.relative_to(Path(item["path"])))
            except ValueError:
                shown = str(path)
            has_settings = part["kind"] == "native" and bool(modpacks.dll_configs(path))
            meta = (tr("включён") if on else tr("выключен")) if part["exists"] else tr("не найден")
            if has_settings and part["exists"]:
                meta += " · " + tr("есть настройки")
            return {"title": path.name, "subtitle": shown, "indent": True,
                    "badge": "DLL" if part["kind"] == "native" else tr("ПАКЕТ"),
                    "status": (OK if on else OFF) if part["exists"] else WARN,
                    "meta": meta, "meta_color": WARN if not part["exists"] else DIM, "dim": not on}

        def redraw(selected=None):
            rows = []
            row_map.clear()
            for i, item in enumerate(profile.get("mods", [])):
                rows.append(mod_row(i, item)); row_map.append(("mod", i, None))
                if profiles.is_me3_pack(item) and Path(item["path"]).exists():
                    for part in profiles.pack_parts(item, coop_on):
                        rows.append(part_row(item, part)); row_map.append(("part", i, part))
            mods.set_rows(rows, selected)

        def row_of_mod(mod_index):
            return next((r for r, (kind, i, _p) in enumerate(row_map) if kind == "mod" and i == mod_index), 0)

        def selected_entry():
            if mods.selected is None or not (0 <= mods.selected < len(row_map)):
                return None
            return row_map[mods.selected]

        def selected_index():
            entry = selected_entry()
            return entry[1] if entry else None

        def add_folder():
            path = filedialog.askdirectory(parent=window, title=tr("Выберите папку распакованного мода"))
            if not path:
                return
            info = modpacks.detect(path)
            if info["type"] == "me3":
                # Модпак со своим профилем ME3 (Convergence, Reforged): встаёт в этот же
                # профиль и разворачивается по профилю автора — вместе с Seamless и модами.
                self._add_pack_entry(profile, path)
                self.manage_mods()
                return
            if info["type"] == "loader":
                # Только свой загрузчик без профиля ME3 — запускается целиком отдельным профилем.
                if messagebox.askyesno(tr("Это модпак"), tr("У этого мода свой загрузчик без профиля Mod Engine 3 — такой мод запускают целиком, как задумал автор.\n\nИмпортировать его как отдельный профиль-модпак?"), parent=window):
                    self.import_modpack(path)
                return
            if info["packages"] == [Path(path)] and not info["dlls"]:
                try:
                    profiles.add_mod(self.data, profile["name"], path, "package")
                    redraw(); mods.select(row_of_mod(len(profile["mods"])-1), notify=False)
                except ValueError as exc:
                    messagebox.showerror(tr("Не удалось добавить мод"), tr(str(exc)), parent=window)
                return
            self._add_mod_files(profile, info, parent=window)

        def settings():
            entry = selected_entry()
            if not entry:
                return
            kind, index, part = entry
            if kind == "part":
                path = Path(part["path"])
                self.mod_settings({"name": path.name, "path": str(path), "kind": part["kind"]}, self.manage_mods)
            else:
                self.mod_settings(profile["mods"][index], self.manage_mods)

        def connect_seamless():
            dll = profiles.find_seamless_in_game(profiles.game_exe(profile["path"]).parent)
            if not dll:
                folder = filedialog.askdirectory(parent=window, title=tr("Папка распакованного Seamless Co-op"))
                if not folder:
                    return
                dll = profiles.find_seamless_in_folder(folder)
                if not dll:
                    return messagebox.showerror(tr("Seamless Co-op не найден"), tr("В папке нет ersc.dll. Скачайте Seamless Co-op с Nexus, распакуйте архив целиком и укажите эту папку."), parent=window)
            profiles.add_seamless(self.data, profile, dll)
            custom = profiles.custom_me3(profile)
            if custom and profiles.add_seamless_to_me3(custom, dll):
                self.log(tr("Seamless вписан в свой .me3 первым, с load_early = true: {path}").format(path=custom))
            self.scene.toast(tr("Seamless Co-op подключён к «{name}»").format(name=profile["name"]))
            self.scene.react("smug")
            self.manage_mods()

        def toggle_seamless():
            coop = profiles.seamless_mod(profile)
            coop["enabled"] = not coop.get("enabled", True)
            profiles.save(self.data)
            self.scene.schedule()
            self.manage_mods()

        def seamless_settings():
            coop = profiles.seamless_mod(profile)
            ini = profiles.seamless_settings_file(coop) if coop else None
            if not ini:
                return messagebox.showerror(tr("Нет настроек"), tr("Рядом с ersc.dll не найден ersc_settings.ini. Переустановите Seamless Co-op."), parent=window)
            self.open_config(ini, self.manage_mods)

        def add_native():
            path = filedialog.askopenfilename(parent=window, title=tr("Выберите DLL-мод"), filetypes=[(tr("DLL-мод"), "*.dll")])
            if not path:
                return
            try:
                profiles.add_mod(self.data, profile["name"], path, "native")
                redraw(); mods.select(row_of_mod(len(profile["mods"])-1), notify=False)
            except ValueError as exc:
                messagebox.showerror(tr("Не удалось добавить DLL"), tr(str(exc)), parent=window)

        def toggle(row=None):
            row = mods.selected if row is None else row
            if row is None or not (0 <= row < len(row_map)):
                return
            kind, index, part = row_map[row]
            if kind == "part":
                profiles.toggle_pack_part(self.data, profile["mods"][index], part["path"])
            else:
                profiles.toggle_mod(self.data, profile["name"], index)
            self.scene.schedule()
            redraw(row)

        def remove():
            entry = selected_entry()
            if not entry:
                return
            kind, index, part = entry
            if kind == "part":
                return messagebox.showinfo(tr("Часть модпака"), tr("Это часть модпака «{pack}». Её нельзя убрать отдельно, но можно выключить — кнопка «Вкл/выкл» или двойной щелчок.").format(pack=profile["mods"][index]["name"]), parent=window)
            if messagebox.askyesno(tr("Убрать мод"), tr("Убрать «{name}» из профиля?\n\nФайлы мода не удаляются.").format(name=profile["mods"][index]["name"]), parent=window):
                profiles.remove_mod(self.data, profile["name"], index)
                redraw()
                mods.select(row_of_mod(max(0, index-1)), notify=False) if profile.get("mods") else None

        def move(direction):
            entry = selected_entry()
            if not entry:
                return
            kind, index, _part = entry
            if kind == "part":
                return self.scene.toast(tr("Порядок внутри модпака задаёт его автор"))
            if 0 <= index+direction < len(profile["mods"]):
                profiles.move_mod(self.data, profile["name"], index, direction)
                redraw()
                mods.select(row_of_mod(index+direction), notify=False)

        def choose_me3():
            path = filedialog.askopenfilename(parent=window, title=tr("Выберите me3.exe"), filetypes=[("Mod Engine 3", "me3.exe"), ("EXE", "*.exe")])
            if path:
                profiles.set_me3_path(self.data, path)
                me3_state.configure(text=path, fg=MUTED)

        def save_options(_event=None):
            profiles.set_profile_option(self.data, profile["name"], "savefile", savefile.get().strip())

        def toggle_online():
            wanted = "online" if online.get() else "offline"
            self.set_launch_mode(wanted, profile)
            online.set(profiles.launch_mode(profile) == "online")  # если пользователь отказался — вернуть

        def conflicts():
            found = profiles.mod_conflicts(profile)
            if not found:
                self.scene.react("smug")
                return messagebox.showinfo(tr("Проверка конфликтов"), tr("Конфликтов нет."), parent=window)
            text = tr("Конфликты файлов ({n}):").format(n=len(found)) + "\n\n" + "\n".join(found[:30])
            if len(found) > 30:
                text += "\n" + tr("… и ещё {n}").format(n=len(found)-30)
            self.scene.react("angry")
            messagebox.showinfo(tr("Проверка конфликтов"), text, parent=window)

        # ── файл профиля ME3: автосборка или свой (ручной) ──
        def pick_custom():
            path = filedialog.askopenfilename(parent=window, title=tr("Выберите файл профиля .me3"),
                                              filetypes=[(tr("Профиль Mod Engine 3"), "*.me3"), (tr("Все файлы"), "*.*")])
            if path:
                profile["me3_custom"] = str(Path(path).resolve())
                profiles.save(self.data)
                self.log(tr("Профиль «{name}» запускается по файлу {path}").format(name=profile["name"], path=path))
                self.manage_mods()

        def create_custom():
            save_options()
            path = profiles.create_custom_me3(self.data, profile)
            self.log(tr("Создан свой .me3: {path}").format(path=path))
            self.edit_me3(profile, path)

        def use_auto():
            profile.pop("me3_custom", None)
            profiles.save(self.data)
            self.scene.toast(tr("Файл .me3 снова собирает лаунчер"))
            self.manage_mods()

        def delete_custom():
            path = profiles.custom_me3(profile)
            if not path:
                return use_auto()
            if profiles.is_own_custom(path):
                if not messagebox.askyesno(tr("Удалить .me3"), tr("Удалить свой файл профиля?\n{path}\n\nПрофиль снова будет запускаться по автосборке лаунчера.").format(path=path), parent=window):
                    return
                remove_file = True
            else:
                answer = messagebox.askyesnocancel(tr("Удалить .me3"), tr("Этот файл не создан лаунчером:\n{path}\n\n«Да» — удалить файл с диска.\n«Нет» — только отвязать от профиля (файл останется).").format(path=path), parent=window)
                if answer is None:
                    return
                remove_file = answer
            if remove_file:
                try:
                    path.unlink()
                    self.log(tr("Удалён файл {path}").format(path=path))
                except OSError as exc:
                    return messagebox.showerror(tr("Не удалось удалить"), str(exc), parent=window)
            use_auto()

        def choose_pack_file(mod, value):
            if value == "?":
                start = mod.get("path") if Path(mod.get("path", "")).is_dir() else None
                value = filedialog.askopenfilename(parent=window, initialdir=start, title=tr("Профиль .me3 модпака «{name}»").format(name=mod["name"]),
                                                   filetypes=[(tr("Профиль Mod Engine 3"), "*.me3"), (tr("Все файлы"), "*.*")])
                if not value:
                    return
            if value:
                mod["me3_file"] = str(Path(value).resolve())
            else:
                mod.pop("me3_file", None)
            mod.pop("pack_disabled", None)  # части другого профиля — список выключенных обнуляем
            profiles.save(self.data)
            self.manage_mods()

        def rescan_pack(mod):
            found = profiles.pack_me3_files(mod["path"], refresh=True)
            self.scene.toast(tr("Найдено файлов .me3: {n}").format(n=len(found)))
            self.manage_mods()

        def me3_menu():
            menu = tk.Menu(window, tearoff=False, bg=PANEL, fg=TEXT, activebackground="#443b2d",
                           activeforeground=GOLD, selectcolor=GOLD, font=(FONT, -15))
            custom = profiles.custom_me3(profile)
            if custom:
                menu.add_command(label=tr("Редактировать свой .me3"), command=lambda: self.edit_me3(profile, custom))
                menu.add_command(label=tr("Открыть папку с файлом"), command=lambda: os.startfile(custom.parent))
                menu.add_command(label=tr("Вернуть автосборку лаунчера"), command=use_auto)
                menu.add_command(label=tr("Удалить свой .me3…"), command=delete_custom)
            else:
                menu.add_command(label=tr("Создать свой .me3 из текущих модов"), command=create_custom)
                menu.add_command(label=tr("Показать .me3, который соберёт лаунчер"), command=lambda: self.edit_me3(profile, None))
            menu.add_command(label=tr("Выбрать готовый файл .me3…"), command=pick_custom)
            menu._vars = []
            for mod in profile.get("mods", []):
                if not profiles.is_me3_pack(mod) or not Path(mod.get("path", "")).is_dir():
                    continue
                sub = tk.Menu(menu, tearoff=False, bg=PANEL, fg=TEXT, activebackground="#443b2d",
                              activeforeground=GOLD, selectcolor=GOLD, font=(FONT, -15))
                current = tk.StringVar(value=mod.get("me3_file", ""))
                menu._vars.append(current)
                auto = profiles.choose_pack_profile(profiles.pack_me3_files(mod["path"]), coop_on,
                                                    profiles.launch_mode(profile) == "online")
                sub.add_radiobutton(label=tr("Автоматически ({file})").format(file=auto.name if auto else "—"),
                                    variable=current, value="", command=lambda m=mod: choose_pack_file(m, ""))
                for file in profiles.pack_me3_files(mod["path"]):
                    try:
                        shown = str(file.relative_to(mod["path"]))
                    except ValueError:
                        shown = str(file)
                    sub.add_radiobutton(label=shown, variable=current, value=str(file.resolve()),
                                        command=lambda m=mod, f=file: choose_pack_file(m, str(f)))
                sub.add_separator()
                sub.add_command(label=tr("Другой файл…"), command=lambda m=mod: choose_pack_file(m, "?"))
                sub.add_command(label=tr("Искать .me3 заново"), command=lambda m=mod: rescan_pack(m))
                menu.add_separator()
                menu.add_cascade(label=tr("Профиль модпака «{name}»").format(name=mod["name"]), menu=sub)
            try:
                menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
            finally:
                menu.grab_release()

        def reset_save():
            name = profiles.profile_savefile(profile)
            if not name:
                return
            if saves.game_running():
                return messagebox.showinfo(tr("Игра запущена"), tr("Закройте игру перед сбросом сохранений."), parent=window)
            files = [f for d in saves.save_dirs() for f in (d / name, d / f"{name}.bak") if f.is_file()]
            if not files:
                return messagebox.showinfo(tr("Сейвов нет"), tr("Файла {name} ещё нет — при следующем запуске игра начнёт с чистого листа.").format(name=name), parent=window)
            if not messagebox.askyesno(tr("Сбросить сейв профиля"), tr("Удалить сохранения этого профиля ({name})?\n\nПеред удалением лаунчер сделает резервную копию всех сохранений — её можно вернуть на вкладке «Сейвы». Основные сохранения игры не трогаются.").format(name=name), parent=window):
                return
            try:
                saves.backup("Перед сбросом сейва профиля", profile["name"])  # переводится при показе
                for f in files:
                    f.unlink()
            except OSError as exc:
                return messagebox.showerror(tr("Не удалось сбросить"), str(exc), parent=window)
            self.log(tr("Сейв профиля «{name}» сброшен: {files}").format(name=profile["name"], files=", ".join(f.name for f in files)))
            self.scene.toast(tr("Сейв профиля сброшен, резервная копия сохранена"))

        # Нижние блоки пакуем первыми (side=bottom), чтобы список занял остаток.
        me3_card = tk.Frame(window, bg=CARD, highlightthickness=1, highlightbackground=CARD_BORDER)
        me3_card.pack(fill="x", side="bottom", padx=20, pady=(0, 16))
        me3_inner = tk.Frame(me3_card, bg=CARD)
        me3_inner.pack(fill="x", padx=18, pady=12)
        me3_top = tk.Frame(me3_inner, bg=CARD)
        me3_top.pack(fill="x")
        tk.Label(me3_top, text="Mod Engine 3", bg=CARD, fg=GOLD, font=(FONT, -16, "bold")).pack(side="left")
        me3 = self._find_me3(profile)
        me3_state = tk.Label(me3_top, text=f"{me3}" if me3 else tr("не найден — укажите me3.exe перед запуском модов"),
                             bg=CARD, fg=MUTED if me3 else WARN, font=(FONT, -12), anchor="w")
        me3_state.pack(side="left", fill="x", expand=True, padx=(12, 8))
        self._button(me3_top, tr("Указать me3.exe"), choose_me3, 170, 38).pack(side="right")
        options = tk.Frame(me3_inner, bg=CARD)
        options.pack(fill="x", pady=(8, 0))
        online = tk.BooleanVar(value=profiles.launch_mode(profile) == "online")
        online_row = tk.Frame(options, bg=CARD)
        online_row.pack(side="left")
        ToggleSwitch(online_row, online, toggle_online).pack(side="left")
        online_label = tk.Label(online_row, text=tr("Официальный онлайн"), bg=CARD, fg=INK, font=(FONT, -14))
        online_label.pack(side="left", padx=(8, 0))
        Tooltip(online_label, tr("Выключено — игра с модами стартует офлайн (рекомендуется). Онлайн с модами может привести к бану."))
        tk.Label(options, text=tr("Отдельный savefile:"), bg=CARD, fg=INK, font=(FONT, -14)).pack(side="left", padx=(24, 6))
        savefile = tk.StringVar(value=profile.get("savefile", ""))
        entry = styled_entry(options, savefile, width=22)
        entry.pack(side="left", ipady=3)
        entry.bind("<FocusOut>", save_options)
        entry.bind("<Return>", save_options)
        Tooltip(entry, tr("Имя файла сохранения для этого профиля, например ER0000.mod.sl2 — так моды не испортят основные сохранения."))
        self._button(options, tr("Файл .me3 ▾"), me3_menu, 150, 38,
                     tooltip=tr("Свой файл профиля ME3: создать, выбрать, редактировать, удалить; выбор профиля модпака")).pack(side="right")
        # Чем запускается профиль и в какой файл идут сохранения.
        status = tk.Frame(me3_inner, bg=CARD)
        status.pack(fill="x", pady=(8, 0))
        custom = profiles.custom_me3(profile)
        if custom:
            how = tr("Свой файл .me3 (ручной режим): {path}").format(path=custom)
        elif profile.get("me3_custom"):
            how = tr("Свой файл .me3 не найден ({path}) — используется автосборка").format(path=profile["me3_custom"])
        else:
            how = tr("Файл .me3 собирает лаунчер из списка модов")
        save_name = profiles.profile_savefile(profile)
        how += "   ·   " + (tr("сейвы: {file}").format(file=save_name) if save_name else tr("сейвы: обычные (ER0000.sl2)"))
        tk.Label(status, text=how, bg=CARD, fg=GOLD if custom else DIM, font=(FONT, -12), anchor="w").pack(side="left", fill="x", expand=True)
        if save_name:
            self._button(status, tr("Сбросить сейв"), reset_save, 140, 32,
                         tooltip=tr("Начать этот профиль с чистого листа (с резервной копией)")).pack(side="right")
        if custom:
            entry.configure(state="disabled")
            Tooltip(entry, tr("В ручном режиме savefile задаётся в самом файле .me3"))

        buttons = tk.Frame(window, bg=PAGE_BG)
        buttons.pack(fill="x", side="bottom", padx=20, pady=(0, 10))
        for text, command, width, tip in (
            (tr("+ Мод"), add_folder, 105, tr("Папка распакованного мода: лаунчер сам найдёт файлы игры и DLL внутри")),
            ("+ DLL", add_native, 90, tr("Добавить отдельный DLL-мод")),
            (tr("Вкл/выкл"), toggle, 100, tr("Двойной щелчок по моду делает то же самое")),
            ("↑", lambda: move(-1), 46, tr("Раньше в порядке загрузки")),
            ("↓", lambda: move(1), 46, tr("Позже в порядке загрузки")),
            (tr("Настройки"), settings, 115, tr("ini-настройки выбранного мода")),
            (tr("Убрать"), remove, 95, tr("Убрать мод из профиля (файлы не удаляются)")),
        ):
            self._button(buttons, text, command, width, 40, tooltip=tip).pack(side="left", padx=(0, 6))
        self._button(buttons, tr("Конфликты"), conflicts, 125, 40,
                     tooltip=tr("Найти файлы, которые есть сразу в нескольких включённых модах")).pack(side="right")

        # Строка Seamless Co-op: кооператив подключается к этому же профилю.
        coop = profiles.seamless_mod(profile)
        game_coop = profiles.find_seamless_in_game(profiles.game_exe(profile["path"]).parent)
        strip = tk.Frame(window, bg=CARD, highlightthickness=1, highlightbackground="#6b5a3a" if coop else CARD_BORDER)
        strip.pack(fill="x", padx=20, pady=(0, 10))
        strip_inner = tk.Frame(strip, bg=CARD)
        strip_inner.pack(fill="x", padx=16, pady=8)
        if coop and coop.get("enabled", True):
            state, color = tr("Seamless Co-op включён — игра идёт в кооперативе Seamless"), OK
            password = ""
            ini = profiles.seamless_settings_file(coop)
            if ini:
                password = next((i["value"] for i in mod_config.read(ini) if i["key"].lower() == "cooppassword"), "")
            if password:
                state += "  ·  " + tr("пароль: {password}").format(password=password)
        elif coop:
            state, color = tr("Seamless Co-op подключён, но выключен"), OFF
        elif game_coop:
            state, color = tr("Seamless Co-op найден в папке игры — подключить к этому профилю?"), GOLD
        else:
            state, color = tr("Seamless Co-op не подключён — кооператив с друзьями без официальных серверов"), OFF
        dot = tk.Canvas(strip_inner, width=12, height=12, bg=CARD, highlightthickness=0)
        dot.create_image(6, 6, image=ui_draw.circle(9, color))
        dot.pack(side="left", padx=(0, 10))
        tk.Label(strip_inner, text=state, bg=CARD, fg=INK, font=(FONT, -14), anchor="w").pack(side="left", fill="x", expand=True)
        if coop:
            self._button(strip_inner, tr("Выключить") if coop.get("enabled", True) else tr("Включить"), toggle_seamless, 120, 36).pack(side="right")
            self._button(strip_inner, tr("Настройки"), seamless_settings, 120, 36,
                         tooltip=tr("Пароль сессии, сложность, вторжения")).pack(side="right", padx=(0, 6))
        else:
            self._button(strip_inner, tr("Подключить") if game_coop else tr("Подключить…"), connect_seamless, 150, 36,
                         tooltip=tr("Seamless Co-op загрузится вместе с остальными модами этого профиля")).pack(side="right")

        mods = CardList(window, on_activate=toggle,
                        empty_text=tr("Модов пока нет.\nНажмите «+ Мод» и укажите папку распакованного мода — лаунчер сам найдёт нужные файлы."),
                        empty_image=self.scene.sprite_photo("read", 140))
        mods.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        mods.bind("<space>", lambda _e: toggle())
        mods.bind("<Delete>", lambda _e: remove())
        redraw(0 if profile.get("mods") else None)
        mods.focus_set()

    def edit_me3(self, profile, path):
        """Редактор файла профиля ME3. path=None — просмотр того, что соберёт лаунчер."""
        set_active_tab(self, "mods")
        readonly = path is None
        subtitle = tr("{name} · так лаунчер соберёт .me3 (только просмотр)").format(name=profile["name"]) if readonly \
            else f"{profile['name']} · {path}"
        window = self._open_tab(".me3", subtitle)
        try:
            text = profiles.render_me3(profile) if readonly else Path(path).read_text(encoding="utf-8-sig")
        except OSError as exc:
            messagebox.showerror(tr("Не удалось открыть"), str(exc), parent=self)
            return self.manage_mods()

        actions = tk.Frame(window, bg=PAGE_BG)
        actions.pack(fill="x", side="bottom", padx=20, pady=(0, 16))
        state = tk.Label(actions, text="", bg=PAGE_BG, fg=DIM, font=(FONT, -13), anchor="w")
        hint = tr("Пути можно писать абсолютные или относительно файла (./../mod). Seamless (ersc.dll) — первым в [[natives]] и с load_early = true.")
        tk.Label(window, text=hint, bg=PAGE_BG, fg=DIM, font=(FONT, -12), anchor="w").pack(fill="x", side="bottom", padx=20, pady=(0, 6))

        box = tk.Frame(window, bg="#11100d", highlightthickness=1, highlightbackground=CARD_BORDER)
        box.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        scroll = ttk.Scrollbar(box, orient="vertical")
        scroll.pack(side="right", fill="y")
        editor = tk.Text(box, bg="#11100d", fg=TEXT, font=("Consolas", -15), wrap="none", relief="flat", undo=True,
                         padx=16, pady=12, yscrollcommand=scroll.set, borderwidth=0,
                         selectbackground="#4a3c20", selectforeground="#fff5d3", insertbackground=GOLD)
        scroll.configure(command=editor.yview)
        editor.pack(fill="both", expand=True)
        editor.insert("1.0", text)
        editor.edit_reset()
        editor.edit_modified(False)
        if readonly:
            editor.configure(state="disabled")

        def check():
            content = editor.get("1.0", "end-1c")
            error = profiles.check_me3_text(content)
            if error:
                state.configure(text=tr(error), fg=WARN)
            elif profiles.seamless_without_early(content):
                state.configure(text=tr("Под ersc.dll (Seamless) нужна строка load_early = true"), fg=WARN)
            else:
                state.configure(text=tr("Файл в порядке"), fg=OK)
            return error

        def check_with_me3():
            if check():
                return
            me3 = self._find_me3(profile)
            if not me3:
                return state.configure(text=tr("me3.exe не найден — проверена только структура файла"), fg=WARN)
            save(quiet=True)
            try:
                result = subprocess.run([str(me3), "profile", "show", "-f", str(path)], capture_output=True, text=True,
                                        timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except (OSError, subprocess.TimeoutExpired) as exc:
                return state.configure(text=str(exc), fg=WARN)
            if result.returncode == 0:
                state.configure(text=tr("ME3 принял файл"), fg=OK)
            else:
                lines = (result.stderr or result.stdout).strip().splitlines()
                message = lines[-1] if lines else ""
                state.configure(text=tr("ME3: {error}").format(error=message[-160:]), fg=WARN)
                self.log(tr("Проверка .me3: {error}").format(error=(result.stderr or result.stdout).strip()[-800:]))

        def save(quiet=False):
            content = editor.get("1.0", "end-1c")
            error = profiles.check_me3_text(content)
            if error and not quiet and not messagebox.askyesno(tr("Ошибка в файле"), tr("{error}\n\nВсё равно сохранить?").format(error=tr(error)), parent=self):
                return False
            try:
                Path(path).write_text(content, encoding="utf-8")
            except OSError as exc:
                messagebox.showerror(tr("Не удалось сохранить"), str(exc), parent=self)
                return False
            editor.edit_modified(False)
            if not quiet:
                state.configure(text=tr("Сохранено"), fg=OK)
                self.scene.toast(tr("Файл .me3 сохранён"))
            return True

        def back():
            if not readonly and editor.edit_modified() and messagebox.askyesno(
                    tr("Несохранённые изменения"), tr("Сохранить изменения в файле .me3?"), parent=self):
                if not save():
                    return
            self.manage_mods()

        def make_own():
            new = profiles.create_custom_me3(self.data, profile)
            self.log(tr("Создан свой .me3: {path}").format(path=new))
            self.edit_me3(profile, new)

        self._button(actions, tr("Назад"), back, 120, 44).pack(side="left", padx=(0, 8))
        if readonly:
            self._button(actions, tr("Сделать своим и редактировать"), make_own, 290, 44,
                         tooltip=tr("Сохранить этот текст как свой .me3 профиля — дальше лаунчер запускает его как есть")).pack(side="left")
        else:
            self._button(actions, tr("Сохранить"), save, 150, 44).pack(side="left", padx=(0, 8))
            self._button(actions, tr("Проверить через ME3"), check_with_me3, 210, 44).pack(side="left", padx=(0, 8))
            self._button(actions, tr("Открыть в блокноте"), lambda: (save(quiet=True), os.startfile(path)), 200, 44).pack(side="left")
            editor.bind("<Control-s>", lambda _e: (save(), "break")[1])
            editor.bind("<Control-S>", lambda _e: (save(), "break")[1])
            editor.focus_set()
        state.pack(side="left", fill="x", expand=True, padx=(12, 0))
        check()

    # ── сохранения ─────────────────────────────────────────────────────

    def show_saves(self):
        set_active_tab(self, "saves")
        window = self._open_tab(self.tt("page.saves"), str(saves.saves_root()))
        settings = self._settings()
        found = saves.save_dirs()

        top = tk.Frame(window, bg=CARD, highlightthickness=1, highlightbackground=CARD_BORDER)
        top.pack(fill="x", padx=20, pady=(0, 12))
        inner = tk.Frame(top, bg=CARD)
        inner.pack(fill="x", padx=18, pady=10)
        auto = tk.BooleanVar(value=settings.get("backup_saves", True))
        keep = tk.IntVar(value=int(settings.get("backup_keep", 10)))

        def store(*_):
            settings["backup_saves"] = auto.get()
            settings["backup_keep"] = int(keep.get())
            profiles.save(self.data)
        columns = tk.Frame(inner, bg=CARD)
        columns.pack(fill="x")
        columns.columnconfigure(0, weight=1, uniform="c")
        columns.columnconfigure(1, weight=1, uniform="c")
        left, right = tk.Frame(columns, bg=CARD), tk.Frame(columns, bg=CARD)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        right.grid(row=0, column=1, sticky="nsew")
        toggle_row(left, tr("Копия перед каждым запуском"), auto,
                   tr("Моды и Seamless иногда портят сохранения — так их всегда можно вернуть."), command=store)
        slider_row(right, keep, 3, 30, tr("Хранить автокопий"), lambda v: str(int(float(v))))
        keep.trace_add("write", store)

        actions = tk.Frame(window, bg=PAGE_BG)
        actions.pack(fill="x", side="bottom", padx=20, pady=(4, 16))
        cards = CardList(window, empty_text=tr("Резервных копий пока нет.\nОни появятся перед запуском игры или по кнопке «Сделать копию».")
                         if found else tr("Сохранения Elden Ring не найдены.\nЗапустите игру хотя бы один раз — они появятся в %APPDATA%\\EldenRing."),
                         empty_image=self.scene.sprite_photo("sleep" if found else "confused", 150))
        cards.pack(fill="both", expand=True, padx=20, pady=(0, 8))
        backups = saves.list_backups()

        def row(meta):
            try:
                created = datetime.fromisoformat(meta["created"]).strftime("%d.%m.%Y, %H:%M:%S")
            except (KeyError, ValueError):
                created = meta.get("created", "?")
            reason = tr(meta.get("reason", ""))
            if meta.get("profile"):
                reason += f" · {meta['profile']}"
            return {"title": created, "subtitle": reason, "badge": tr("АВТО") if meta.get("auto") else tr("ВРУЧНУЮ"),
                    "status": OK, "meta": tr("{files} файл. · {size:.1f} МБ").format(files=meta.get("files", 0), size=meta.get("size", 0)/2**20)}
        cards.set_rows([row(m) for m in backups], 0 if backups else None)

        def selected():
            return backups[cards.selected] if backups and cards.selected is not None else None

        def create():
            path = saves.backup("Вручную")
            if path:
                self.scene.toast(tr("Копия сохранений создана"))
                self.scene.react("smug")
                self.show_saves()
            else:
                messagebox.showinfo(tr("Нечего копировать"), tr("Сохранения Elden Ring не найдены."), parent=self)

        def restore():
            meta = selected()
            if not meta:
                return
            if saves.game_running():
                self.scene.react("angry")
                return messagebox.showwarning(tr("Игра запущена"), tr("Закройте Elden Ring перед восстановлением сохранений."), parent=self)
            if not messagebox.askyesno(tr("Восстановить сохранения"), tr("Вернуть сохранения из копии {date}?\n\nТекущие сохранения сначала будут скопированы — их тоже можно будет вернуть.\nSteam Cloud может предложить выбрать версию при следующем запуске — выберите локальную.").format(date=row(meta)["title"]), parent=self):
                return
            try:
                saves.restore(meta["path"])
            except OSError as exc:
                self.scene.react("dizzy")
                return messagebox.showerror(tr("Не удалось восстановить"), str(exc), parent=self)
            self.scene.toast(tr("Сохранения восстановлены"))
            self.scene.react("smug")
            self.show_saves()

        def delete():
            meta = selected()
            if meta and messagebox.askyesno(tr("Удалить копию"), tr("Удалить резервную копию {date}?").format(date=row(meta)["title"]), parent=self):
                saves.delete(meta["path"])
                self.show_saves()

        cards.on_activate = lambda _i: restore()
        cards.bind("<Delete>", lambda _e: delete())
        self._button(actions, tr("Сделать копию"), create, 170, 46, small=False, enabled=bool(found)).pack(side="left", padx=(0, 8))
        self._button(actions, tr("Восстановить"), restore, 170, 46, small=False, enabled=bool(backups)).pack(side="left", padx=(0, 8))
        self._button(actions, tr("Удалить"), delete, 130, 46, small=False, enabled=bool(backups)).pack(side="left", padx=(0, 8))
        self._button(actions, tr("Папка сохранений"), lambda: os.startfile(saves.saves_root()), 190, 46,
                     enabled=saves.saves_root().is_dir()).pack(side="right")
        self._button(actions, tr("Папка копий"), lambda: os.startfile(saves.backups_root()), 150, 46).pack(side="right", padx=(0, 8))

    def _auto_backup(self, profile):
        if not self._settings().get("backup_saves", True):
            return
        try:
            if saves.backup("Перед запуском", profile["name"], auto=True):
                saves.prune(int(self._settings().get("backup_keep", 10)))
        except OSError as exc:
            self.log(tr("Не удалось сделать копию сохранений: {error}").format(error=exc))

    # ── запуск и время в игре ──────────────────────────────────────────

    def launch(self):
        if self.launch_pending or self.operation_running or self.copy_running:
            return
        self.launch_pending = True
        self.scene.schedule()
        try:
            p = self._profile()
            if p and saves.game_running():
                self.scene.react("silent")
                messagebox.showinfo(tr("Игра уже запущена"), tr("Elden Ring уже работает. Закройте его, чтобы запустить другой профиль."), parent=self)
                return
            if p and profiles.game_exe(p["path"]).is_file():
                self._auto_backup(p)
            if p and not self._prepare_loaders(p):
                return
            launched = self._launch_profile()
            if not launched:
                self._restore_loaders()
            if launched:
                p = self._profile()
                p["last_played"] = datetime.now().strftime("%d.%m, %H:%M")
                profiles.save(self.data)
                self.scene.toast(tr("Запускаю «{name}»…").format(name=p["name"]))
                self.scene.react("bonfire", 6)
                self.log(tr("Запуск профиля «{name}»").format(name=p["name"]))
                self._start_playtime(p["name"])
                if self._settings().get("minimize_on_launch"):
                    self.restore_after_game = True
                    self.after(800, self.hide_to_tray)
        except OSError as exc:
            self.scene.react("dizzy")
            messagebox.showerror(tr("Не удалось запустить игру"), str(exc), parent=self)
        finally:
            self.after(2000, self._clear_launch_pending)

    # ── сторонние загрузчики модов в папке игры (dinput8.dll и т. п.) ────

    def _loaders_apply(self, p):
        """Запуск без EAC: сторонние DLL из папки игры загрузятся вместе с ней."""
        via_me3 = p.get("kind") == "pack" or any(m.get("enabled", True) for m in p.get("mods", []))
        return via_me3 or profiles.launch_mode(p) != "online"  # чистый онлайн идёт через EAC — он их не пустит

    def _prepare_loaders(self, p):
        """Спрашивает (один раз для профиля), отключать ли сторонние загрузчики
        на время игры. False — пользователь отменил запуск."""
        exe = profiles.game_exe(p["path"])
        found = profiles.foreign_loaders(exe.parent) if exe.is_file() else []
        if not found or not self._loaders_apply(p):
            return True
        names = ", ".join(profiles.foreign_loader_label(f) for f in found)
        choice = p.get("foreign_loaders")
        if choice not in ("disable", "keep"):
            self.scene.react("confused")
            answer = messagebox.askyesnocancel(
                tr("Сторонние загрузчики модов"),
                tr("В папке игры найдены сторонние загрузчики модов:\n{names}\n\n"
                   "Без Easy Anti-Cheat игра загрузит их вместе с собой. Старые моды через них часто ломают "
                   "управление (персонаж не ходит, только поворачивается), камеру или вызывают вылеты.\n\n"
                   "«Да» — отключать их на время игры из лаунчера (после выхода файлы вернутся на место).\n"
                   "«Нет» — оставить как есть.\n\nВыбор запомнится для профиля «{name}»; изменить можно в меню профиля.").format(
                    names=names, name=p["name"]), parent=self)
            if answer is None:
                return False
            choice = "disable" if answer else "keep"
            p["foreign_loaders"] = choice
            profiles.save(self.data)
        if choice == "keep":
            self.log(tr("Сторонние загрузчики остаются включёнными: {names}").format(names=names))
            return True
        renamed = profiles.disable_loaders(exe.parent)
        if renamed:
            settings = self._settings()
            settings["renamed_loaders"] = sorted(set(settings.get("renamed_loaders", [])) | set(renamed))
            profiles.save(self.data)
            self.log(tr("Отключены на время игры: {names}").format(names=names))
        if len(renamed) < len(found):
            self.log(tr("Не удалось отключить часть загрузчиков (нет прав на запись в папку игры?)"))
        return True

    def _restore_loaders(self):
        settings = self._settings()
        pending = settings.get("renamed_loaders")
        if not pending:
            return
        left = profiles.restore_loaders(pending)
        if len(left) < len(pending):
            self.log(tr("Сторонние загрузчики возвращены на место"))
        if left:
            settings["renamed_loaders"] = left
        else:
            settings.pop("renamed_loaders", None)
        profiles.save(self.data)

    def set_loader_choice(self, choice):
        p = self._profile()
        if p:
            p["foreign_loaders"] = choice
            profiles.save(self.data)
            self.scene.toast(tr("Сторонние загрузчики: {state}").format(
                state=tr("отключаются на время игры") if choice == "disable" else tr("загружаются вместе с игрой")))

    def _clear_launch_pending(self):
        self.launch_pending = False
        self.scene.schedule()

    def _start_playtime(self, name):
        """Считает время, пока работает eldenring.exe (ME3 и Seamless запускают
        его не сразу, поэтому ждём появления процесса до двух минут)."""
        if self.playtime_thread and self.playtime_thread.is_alive():
            return

        def push(seconds, final=False):
            def apply():
                profile = self._find_profile(name)
                if profile and seconds:
                    profile["playtime"] = profile.get("playtime", 0) + seconds
                    profiles.save(self.data)
                    self.scene.schedule()
                if final:
                    self._game_closed(name)
            try:
                self.after(0, apply)
            except RuntimeError:
                pass

        def watch():
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline and not saves.game_running():
                time.sleep(3)
            if not saves.game_running():
                push(0, final=True)
                return
            pending, last = 0.0, time.monotonic()
            self.game_running = True  # фон не меняем, пока игра занимает память
            while saves.game_running():
                time.sleep(10)
                now = time.monotonic()
                pending += now - last
                last = now
                if pending >= 60:
                    push(pending)
                    pending = 0.0
            self.game_running = False
            push(pending, final=True)
        self.playtime_thread = threading.Thread(target=watch, daemon=True)
        self.playtime_thread.start()

    def _game_closed(self, name):
        profile = self._find_profile(name)
        self._restore_loaders()
        self.log(tr("Игра закрыта · профиль «{name}»").format(name=name))
        if profile and profile.get("playtime"):
            self.scene.toast(tr("Всего в «{name}»: {time}").format(
                name=name, time=profiles.format_playtime(profile["playtime"], i18n.LANG)), 4)
        if self.restore_after_game:
            self.restore_after_game = False
            if self.state() in ("withdrawn", "iconic"):
                self.restore_from_tray()

    def _launch_profile(self):
        p = self._profile()
        if not p:
            messagebox.showinfo(tr("Выберите профиль"), tr("Выберите профиль в библиотеке."), parent=self)
            return False
        if p.get("kind") == "pack" and p.get("pack_type") == "loader":
            return self._launch_pack(p)
        self._ensure_pack_entry(p)
        exe = profiles.game_exe(p["path"])
        if not exe.is_file():
            messagebox.showerror(tr("Не найден exe"), str(exe), parent=self)
            return False
        enabled = [item for item in p.get("mods", []) if item.get("enabled", True)]
        coop = profiles.seamless_mod(p, enabled_only=True)
        if coop and not Path(coop["path"]).is_file():
            messagebox.showerror(tr("Seamless Co-op не найден"), tr("Файл Seamless Co-op не найден:\n{path}\n\nПодключите его заново во вкладке «Моды».").format(path=coop["path"]), parent=self)
            return False
        custom = profiles.custom_me3(p)
        if p.get("me3_custom") and not custom:
            self.log(tr("Свой файл .me3 не найден ({path}) — используется автосборка").format(path=p["me3_custom"]))
        if enabled or p.get("savefile") or custom:
            me3 = self._find_me3(p)
            if not me3 and coop and len(enabled) == 1 and not custom:
                # Только Seamless и нет ME3 — запускаем его собственным лаунчером.
                launcher = next((c for c in (Path(coop["path"]).parent.parent / "ersc_launcher.exe",
                                             exe.parent / "ersc_launcher.exe") if c.is_file()), None)
                if launcher:
                    subprocess.Popen([str(launcher)], cwd=str(launcher.parent))
                    return True
            if not me3:
                messagebox.showerror(tr("Mod Engine 3 не найден"),
                                     tr("Откройте вкладку «Моды», нажмите «Указать me3.exe» и выберите официальный me3.exe."), parent=self)
                return False
            manifest = profiles.write_me3_profile(self.data, p)
            self.log(tr("Mod Engine 3: {me3} · профиль {path}").format(me3=me3, path=manifest))
            command = self._me3_command(me3, manifest, exe)
            mode = profiles.launch_mode(p)
            if mode in ("online", "offline"):  # режим профиля; Seamless сам решает, куда подключаться
                command += ["--online", "true" if mode == "online" else "false"]
            try:
                subprocess.Popen(command, cwd=str(me3.parent))
            except OSError as exc:
                messagebox.showerror(tr("Не удалось запустить ME3"), str(exc), parent=self)
                return False
            return True
        return self._launch_vanilla(p, exe)

    def _launch_vanilla(self, p, exe):
        game_dir = exe.parent
        if profiles.launch_mode(p) == "online":
            # Онлайн: через лаунчер Easy Anti-Cheat, как это делает Steam.
            eac = game_dir / "start_protected_game.exe"
            if not eac.is_file():
                messagebox.showerror(tr("Онлайн недоступен"), tr("В папке профиля нет start_protected_game.exe (лаунчер Easy Anti-Cheat). Переключите профиль в офлайн или проверьте файлы игры в Steam."), parent=self)
                return False
            if self._in_steam_library(exe):
                # Игра из Steam-библиотеки — запускаем через сам Steam, ровно как кнопка «Играть» в Steam
                # (Steam Input, оверлей и EAC работают как обычно).
                os.startfile(f"steam://rungameid/{profiles.STEAM_APP_ID}")
                return True
            if not steam_checks.steam_running():
                messagebox.showerror(tr("Steam не запущен"), tr("Для онлайна нужен запущенный Steam. Запустите его или переключите профиль в офлайн."), parent=self)
                return False
            self._write_appid(game_dir)  # копия вне Steam: иначе Steam перезапустит игру из своей библиотеки
            subprocess.Popen([str(eac)], cwd=str(game_dir))
            return True
        # Офлайн: steam_appid.txt + прямой запуск eldenring.exe — без EAC и серверов.
        if not self._write_appid(game_dir):
            return False
        subprocess.Popen([str(exe)], cwd=str(game_dir))
        return True

    def _launch_pack(self, p):
        """Модпак запускается так, как задумал автор: своим профилем ME3 или своим загрузчиком."""
        folder = Path(p.get("pack_dir", ""))
        if not folder.is_dir():
            messagebox.showerror(tr("Модпак не найден"), tr("Папка модпака не найдена:\n{path}").format(path=folder), parent=self)
            return False
        if p.get("pack_type") == "loader":
            launcher = Path(p.get("pack_launcher", ""))
            if not launcher.is_file():
                messagebox.showerror(tr("Загрузчик не найден"), tr("Файл запуска модпака не найден:\n{path}").format(path=launcher), parent=self)
                return False
            new_console = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            if launcher.suffix.lower() in (".bat", ".cmd"):
                subprocess.Popen(["cmd", "/c", str(launcher)], cwd=str(launcher.parent), creationflags=new_console)
            elif p.get("pack_config"):
                subprocess.Popen([str(launcher), "-t", "er", "-c", str(p["pack_config"])], cwd=str(launcher.parent))
            else:
                subprocess.Popen([str(launcher)], cwd=str(launcher.parent))
            return True
        # Модпак с готовым профилем ME3 (например, Reforged).
        exe = profiles.game_exe(p["path"])
        if not exe.is_file():
            messagebox.showerror(tr("Не найдена игра"), tr("Для модпака не найдена игра. Откройте меню профиля → «Исправить путь» и укажите папку Game."), parent=self)
            return False
        online = profiles.launch_mode(p) == "online"
        me3_files = [Path(f) for f in p.get("pack_me3", []) if Path(f).is_file()]
        profile_file = modpacks.preferred_me3_profile(me3_files, online)
        if not profile_file:
            messagebox.showerror(tr("Профиль ME3 не найден"), tr("В папке модпака больше нет файлов .me3. Импортируйте модпак заново."), parent=self)
            return False
        bundled = p.get("pack_me3_exe")
        if bundled and "linux" in {part.lower() for part in Path(bundled).parts}:
            bundled = None  # старые импорты могли выбрать сборку для Proton
        me3 = Path(bundled) if bundled and Path(bundled).is_file() else self._find_me3(p)
        if not me3:
            messagebox.showerror(tr("Mod Engine 3 не найден"), tr("Модпак использует Mod Engine 3, но он не найден ни в папке модпака, ни в системе. Установите ME3."), parent=self)
            return False
        subprocess.Popen(self._me3_command(me3, profile_file, exe) + ["--online", "true" if online else "false"],
                         cwd=str(profile_file.parent))
        return True

    @staticmethod
    def _in_steam_library(exe):
        return "steamapps" in {part.lower() for part in Path(exe).parts}

    @staticmethod
    def _me3_command(me3, profile_file, exe):
        """Запуск как в официальных модпаках (Start_Convergence.bat):
        me3 launch --auto-detect -p <профиль.me3> — ME3 сам находит игру в Steam
        и сам инициализирует Steam (это нужно Seamless Co-op). Путь к exe
        передаётся только для копий игры вне Steam-библиотеки."""
        in_steam = "steamapps" in {part.lower() for part in Path(exe).parts}
        if in_steam:
            return [str(me3), "launch", "--auto-detect", "-p", str(profile_file)]
        return [str(me3), "launch", "--auto-detect", "-p", str(profile_file), "--exe", str(exe)]

    # ── модпаки и настройки модов ─────────────────────────────────────

    def import_modpack(self, folder=None):
        """Импорт распакованного мода: сам определяет, как его запускать."""
        folder = folder or filedialog.askdirectory(title=tr("Папка распакованного мода или модпака"), parent=self)
        if not folder:
            return
        info = modpacks.detect(folder)
        if info["type"] == "files":
            target = self._profile()
            if not target or target.get("kind") not in ("vanilla", "mods"):
                return messagebox.showinfo(tr("Обычный мод"), tr("Это обычный мод без своего загрузчика. Выберите в библиотеке ванильный или мод-профиль и добавьте мод на вкладке «Моды»."), parent=self)
            return self._add_mod_files(target, info, parent=self)
        base = self._base_game_profile()
        if info["type"] == "me3" and not base:
            return messagebox.showerror(tr("Нет игры"), tr("Модпак запускается через Mod Engine 3 и использует вашу игру. Сначала добавьте игру в библиотеку."), parent=self)
        kind_text = tr("готовый профиль Mod Engine 3") if info["type"] == "me3" else tr("свой загрузчик ({name})").format(name=Path(info["launcher"]).name)
        name = simpledialog.askstring(tr("Импорт модпака"), tr("Найден модпак: {kind}.\n\nНазвание профиля:").format(kind=kind_text),
                                      initialvalue=Path(folder).name, parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        if not self._confirm_new_name(name):
            return
        profiles.add(self.data, name, base["path"] if base else str(folder), "pack")
        p = self._find_profile(name)
        p.update({"pack_dir": str(Path(folder).resolve()), "pack_type": info["type"], "launch_mode": "offline"})
        if info["type"] == "me3":
            p["pack_me3"] = [str(f) for f in info["me3_profiles"]]
            if info["me3_exe"]:
                p["pack_me3_exe"] = str(info["me3_exe"])
            # Модпак с профилем ME3 — элемент списка модов: так к нему можно
            # подключить Seamless Co-op и свои моды в этом же профиле.
            self._add_pack_entry(p, folder, quiet=True)
        else:
            p["pack_launcher"] = str(info["launcher"])
            if info.get("me2_config"):
                p["pack_config"] = str(info["me2_config"])
        if base and base.get("game_version"):
            p["game_version"] = base["game_version"]
        profiles.save(self.data)
        self.refresh()
        self._select_by_name(name)
        self.scene.toast(tr("Модпак «{name}» добавлен").format(name=name))
        self.scene.react("smug")
        self._refresh_open_page()

    def import_me3_file(self, path=None):
        """Новый профиль, который запускается напрямую по выбранному файлу .me3."""
        path = path or filedialog.askopenfilename(parent=self, title=tr("Выберите файл профиля .me3"),
                                                  filetypes=[(tr("Профиль Mod Engine 3"), "*.me3"), (tr("Все файлы"), "*.*")])
        if not path:
            return
        path = Path(path).resolve()
        error = profiles.check_me3_text(path.read_text(encoding="utf-8-sig")) if path.is_file() else tr("Файл не найден")
        if error and not messagebox.askyesno(tr("Ошибка в файле"), tr("{error}\n\nВсё равно добавить?").format(error=tr(error)), parent=self):
            return
        base = self._base_game_profile()
        if not base:
            return messagebox.showerror(tr("Нет игры"), tr("Модпак запускается через Mod Engine 3 и использует вашу игру. Сначала добавьте игру в библиотеку."), parent=self)
        default = path.parent.parent.name if path.parent.name.lower() == "me3" else path.parent.name
        name = simpledialog.askstring(tr("Профиль из .me3"), tr("Файл: {file}\n\nНазвание профиля:").format(file=path.name),
                                      initialvalue=default or path.stem, parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        if not self._confirm_new_name(name):
            return
        profiles.add(self.data, name, base["path"], "pack")
        p = self._find_profile(name)
        p.update({"pack_dir": str(path.parent), "pack_type": "me3file", "me3_custom": str(path), "launch_mode": "offline"})
        if base.get("game_version"):
            p["game_version"] = base["game_version"]
        profiles.save(self.data)
        self.log(tr("Профиль «{name}» запускается по файлу {path}").format(name=name, path=path))
        self.refresh()
        self._select_by_name(name)
        self.scene.toast(tr("Профиль «{name}» добавлен").format(name=name))
        self.scene.react("smug")
        self._refresh_open_page()

    def _add_pack_entry(self, profile, folder, quiet=False):
        """Модпак как элемент списка модов. Если внутри модпака лежит Seamless
        Co-op, а к профилю он ещё не подключён, — подключает и его."""
        folder = Path(folder).resolve()
        mods = profile.setdefault("mods", [])
        if not any(Path(m["path"]).resolve() == folder for m in mods if not profiles.is_seamless(m)):
            mods.append({"name": folder.name, "path": str(folder), "kind": "pack", "enabled": True})
        bundled = profiles.find_seamless_in_game(folder)
        if bundled and not profiles.seamless_mod(profile):
            profiles.add_seamless(self.data, profile, bundled)
        profiles.save(self.data)
        if not quiet:
            self.scene.toast(tr("Модпак «{name}» добавлен в профиль").format(name=folder.name))
            self.scene.react("smug")

    def _ensure_pack_entry(self, profile):
        """Профили-модпаки старого формата (без элемента в списке модов)."""
        if profile.get("kind") == "pack" and profile.get("pack_type") == "me3" and profile.get("pack_dir"):
            if not any(profiles.is_me3_pack(m) for m in profile.get("mods", [])):
                self._add_pack_entry(profile, profile["pack_dir"], quiet=True)

    def _find_me3(self, profile):
        """me3.exe: указанный в лаунчере/установленный, иначе встроенный в модпак."""
        me3 = profiles.find_me3(self.data)
        if me3:
            return me3
        custom = profiles.custom_me3(profile)
        if custom:  # готовый .me3 из модпака: me3.exe обычно лежит рядом
            for candidate in (custom.parent / "Windows" / "me3.exe", custom.parent / "me3.exe",
                              custom.parent.parent / "me3" / "Windows" / "me3.exe"):
                if candidate.is_file():
                    return candidate
        for mod in profile.get("mods", []):
            if profiles.is_me3_pack(mod):
                for candidate in (Path(mod["path"]) / "me3" / "Windows" / "me3.exe", Path(mod["path"]) / "me3" / "me3.exe",
                                  Path(mod["path"]) / "me3.exe"):
                    if candidate.is_file():
                        return candidate
        return None

    def _base_game_profile(self):
        """Игра для модпака: выбранный профиль, если он с игрой, иначе первая ваниль."""
        current = self._profile()
        candidates = ([current] if current else []) + [p for p in self.data["profiles"] if p.get("kind") == "vanilla"]
        for p in candidates:
            if p and p.get("kind") in ("vanilla", "mods") and profiles.game_exe(p["path"]).is_file():
                return p
        return None

    def _add_mod_files(self, profile, info, parent=None):
        """Добавляет в профиль найденные корни пакетов и DLL (с подтверждением)."""
        packages, dlls = info.get("packages", []), info.get("dlls", [])
        if not packages and not dlls:
            return messagebox.showerror(tr("Мод не распознан"), tr("В папке не найдено ни файлов игры (regulation.bin, chr, parts…), ни DLL. Проверьте, что архив распакован полностью."), parent=parent or self)
        lines = [f"• {tr('пакет')}: {p}" for p in packages] + [f"• DLL: {d}" for d in dlls]
        if not messagebox.askyesno(tr("Добавить мод"), tr("В профиль «{name}» будет добавлено:\n\n{items}").format(
                name=profile["name"], items="\n".join(lines[:12]) + ("\n…" if len(lines) > 12 else "")), parent=parent or self):
            return
        added = 0
        for path in packages:
            try:
                profiles.add_mod(self.data, profile["name"], str(path), "package"); added += 1
            except ValueError:
                pass
        for path in dlls:
            if Path(path).name.lower() == profiles.SEAMLESS_DLL:
                profiles.add_seamless(self.data, profile, path); added += 1
                continue
            try:
                profiles.add_mod(self.data, profile["name"], str(path), "native"); added += 1
            except ValueError:
                pass
        self.scene.toast(tr("Добавлено модов: {n}").format(n=added))
        self._refresh_open_page()

    def _pack_page(self, profile):
        folder = Path(profile.get("pack_dir", ""))
        window = self._open_tab(self.tt("page.mods"), tr("{name} · модпак").format(name=profile["name"]))
        card = page_section(window, tr("Модпак"))
        if profile.get("pack_type") == "me3":
            how = tr("Запуск через Mod Engine 3 по профилю мода. Режим онлайн/офлайн переключается на главной.")
            files = ", ".join(Path(f).name for f in profile.get("pack_me3", []))
            extra = tr("Профили ME3: {files}").format(files=files)
        else:
            how = tr("Запуск собственным загрузчиком модпака — так, как задумал автор.")
            extra = tr("Файл запуска: {file}").format(file=Path(profile.get("pack_launcher", "")).name)
        for text, color in ((how, INK), (extra, DIM), (str(folder), DIM)):
            label = tk.Label(card, text=text, bg=CARD, fg=color, font=(FONT, -14 if color == INK else -12), anchor="w", justify="left")
            label.pack(anchor="w", fill="x", pady=(6, 0))
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", pady=(12, 0))
        self._button(row, tr("Открыть папку"), lambda: os.startfile(folder), 160, 40, enabled=folder.is_dir()).pack(side="left", padx=(0, 8))
        self._button(row, tr("Обновить"), lambda: self._redetect_pack(profile), 140, 40,
                     tooltip=tr("Заново определить загрузчик и профили, если модпак обновился")).pack(side="left")
        configs = modpacks.pack_configs(folder) if folder.is_dir() else []
        self._configs_list(window, configs, tr("Настройки модов внутри модпака не найдены (ini/toml)."), back=self.manage_mods)

    def _redetect_pack(self, profile):
        info = modpacks.detect(profile.get("pack_dir", ""))
        if info["type"] == "files":
            return messagebox.showerror(tr("Модпак не распознан"), tr("В папке больше нет загрузчика или профиля ME3."), parent=self)
        profile["pack_type"] = info["type"]
        if info["type"] == "me3":
            profile["pack_me3"] = [str(f) for f in info["me3_profiles"]]
            profile["pack_me3_exe"] = str(info["me3_exe"]) if info["me3_exe"] else ""
        else:
            profile["pack_launcher"] = str(info["launcher"])
            profile["pack_config"] = str(info["me2_config"]) if info.get("me2_config") else ""
        profiles.save(self.data)
        self.scene.toast(tr("Модпак обновлён"))
        self.manage_mods()

    def _configs_list(self, window, configs, empty_text, back):
        cards = CardList(window, on_activate=lambda i: self.open_config(configs[i], back),
                         empty_text=empty_text, empty_image=self.scene.sprite_photo("read", 120))
        cards.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        cards.set_rows([{"title": f.name, "subtitle": str(f), "badge": f.suffix.lstrip(".").upper(),
                         "status": OK if f.suffix.lower() == ".ini" else OFF,
                         "meta": tr("редактор") if f.suffix.lower() == ".ini" else tr("открыть файл")} for f in configs])
        return cards

    def open_config(self, path, back, _values=None):
        """Адаптивная страница настроек мода: виджеты подбираются по значению,
        комментарию и имени ключа; подписи и подсказки переводятся."""
        path = Path(path)
        if path.suffix.lower() != ".ini":
            return os.startfile(path)
        try:
            items = mod_config.read(path)
        except OSError as exc:
            return messagebox.showerror(tr("Не удалось открыть"), str(exc), parent=self)
        if not items:
            return os.startfile(path)
        schema = seamless.KNOWN if path.name.lower() in ("ersc_settings.ini", "seamlesscoopsettings.ini") else None
        specs = [(item, mod_config.infer(item, schema)) for item in items]
        translate = i18n.LANG == "ru" and self._settings().get("translate_configs", True)

        def text_for(source, known=False):
            if known:
                return tr(source)
            if not translate:
                return source
            return translator.cached(source) or source

        # Недостающие переводы — в фоне; когда придут, страница перерисуется
        # с уже введёнными значениями.
        if translate:
            pending = [translator.humanize(item["key"]) for item, spec in specs if not spec["known"]]
            pending += [spec["hint"] for _item, spec in specs if spec["hint"] and not spec["known"]]
            pending += [name for _item, spec in specs for value, name in spec.get("choices", []) if value != name]
            if not schema:
                pending += [translator.humanize(s) for s in dict.fromkeys(item["section"] for item in items) if s]

            # Фоновый поток только кладёт переводы в кэш; окно само проверяет
            # кэш раз в полсекунды (Tk из чужого потока не трогаем).
            if translator.translate_async(pending, lambda _result: None):
                self.after(500, lambda: self._poll_translations(path, back, widgets, pending, 24))

        title = tr("Seamless Co-op") if schema else tr("Настройки мода")
        window = self._open_tab(title, path.name)
        scroll = ScrollFrame(window, PAGE_BG)
        scroll.pack(fill="both", expand=True, pady=(0, 10))
        widgets = {}
        initial = _values or {}
        titles = {"PASSWORD": tr("Сессия"), "GAMEPLAY": tr("Игровой процесс"), "SCALING": tr("Сложность за каждого игрока"),
                  "SAVE": tr("Сохранения"), "LANGUAGE": tr("Язык")} if schema else {}
        sections = list(dict.fromkeys(item["section"] for item in items))
        columns = tk.Frame(scroll.inner, bg=PAGE_BG)
        columns.pack(fill="both", expand=True)
        two = len(sections) > 1
        columns.columnconfigure(0, weight=1, uniform="col")
        if two:
            columns.columnconfigure(1, weight=1, uniform="col")
        cols = [tk.Frame(columns, bg=PAGE_BG), tk.Frame(columns, bg=PAGE_BG)]
        cols[0].grid(row=0, column=0, sticky="nsew")
        if two:
            cols[1].grid(row=0, column=1, sticky="nsew")
        heights = [0, 0]
        for section in sections:
            entries = [(i, s) for i, s in specs if i["section"] == section]
            col = 0 if not two or heights[0] <= heights[1] else 1
            heights[col] += len(entries)+1
            pad = (20, 20) if not two else ((20, 7) if col == 0 else (7, 20))
            heading = titles.get(section.upper()) or (text_for(translator.humanize(section)) if section else tr("Основное"))
            card = page_section(cols[col], heading, padx=pad)
            for item, spec in entries:
                key = (item["section"], item["key"])
                label = text_for(spec["label"], True) if spec["known"] else text_for(translator.humanize(item["key"]))
                if not spec["known"] and label != item["key"] and translate:
                    label = f"{label}  ·  {item['key']}"
                hint = text_for(spec["hint"], spec["known"]) if spec["hint"] else None
                current = initial.get(key, item["value"])
                kind = spec["kind"]
                if kind in ("bool", "bool01"):
                    on = current.lower() in ("true", "1")
                    var = tk.BooleanVar(value=on)
                    toggle_row(card, label, var, hint)
                elif kind == "slider":
                    is_float = spec.get("float")
                    try:
                        number = float(current)
                    except ValueError:
                        number = spec["lo"]
                    var = tk.DoubleVar(value=number) if is_float else tk.IntVar(value=int(round(number)))
                    lo, hi = (spec["lo"], spec["hi"]) if is_float else (int(spec["lo"]), int(spec["hi"]))
                    slider_row(card, var, lo, hi, label,
                               (lambda v: f"{float(v):.2f}".rstrip("0").rstrip(".")) if is_float else (lambda v: str(int(float(v)))),
                               step=spec["step"], hint=hint)
                elif kind == "color":
                    row = tk.Frame(card, bg=CARD)
                    row.pack(fill="x", pady=(10, 0))
                    tk.Label(row, text=label, bg=CARD, fg=INK, font=(FONT, -15), anchor="w").pack(side="left", fill="x", expand=True)
                    var = tk.StringVar(value=current)
                    prefix = "#" if current.startswith("#") else ""
                    swatch = tk.Canvas(row, width=34, height=24, bg=CARD, highlightthickness=1,
                                       highlightbackground=CARD_BORDER, cursor="hand2")

                    def paint(*_a, v=var, s=swatch):
                        code = v.get().strip().lstrip("#")
                        s.configure(bg=f"#{code}" if re.fullmatch(r"[0-9a-fA-F]{6}", code) else CARD)

                    def pick(_e=None, v=var, p=prefix):
                        from tkinter import colorchooser
                        code = v.get().strip().lstrip("#")
                        chosen = colorchooser.askcolor(color=f"#{code}" if re.fullmatch(r"[0-9a-fA-F]{6}", code) else None,
                                                       parent=self)[1]
                        if chosen:
                            v.set(p + chosen.lstrip("#").lower())
                    var.trace_add("write", paint)
                    paint()
                    swatch.bind("<Button-1>", pick)
                    styled_entry(row, var, width=10).pack(side="right", ipady=3, padx=(8, 0))
                    swatch.pack(side="right")
                elif kind == "choice":
                    row = tk.Frame(card, bg=CARD)
                    row.pack(fill="x", pady=(10, 0))
                    text_col = tk.Frame(row, bg=CARD)
                    text_col.pack(side="left", fill="x", expand=True)
                    tk.Label(text_col, text=label, bg=CARD, fg=INK, font=(FONT, -15), anchor="w").pack(anchor="w")
                    if hint:
                        tk.Label(text_col, text=hint, bg=CARD, fg=DIM, font=(FONT, -12), anchor="w",
                                 wraplength=420, justify="left").pack(anchor="w", fill="x")
                    shown = [f"{text_for(name)}" if v == name else f"{v} — {text_for(name)}" for v, name in spec["choices"]]
                    values = [v for v, _name in spec["choices"]]
                    var = tk.StringVar(value=current)
                    box = ttk.Combobox(row, values=shown, state="readonly", width=24, font=(FONT, -14))
                    box.current(values.index(current) if current in values else 0)
                    box.bind("<<ComboboxSelected>>", lambda _e, b=box, v=var, vals=values: v.set(vals[b.current()]))
                    box.pack(side="right", padx=(12, 0))
                else:
                    row = tk.Frame(card, bg=CARD)
                    row.pack(fill="x", pady=(10, 0))
                    text_col = tk.Frame(row, bg=CARD)
                    text_col.pack(side="left", fill="x", expand=True)
                    tk.Label(text_col, text=label, bg=CARD, fg=INK, font=(FONT, -15), anchor="w").pack(anchor="w")
                    if hint:
                        hint_label = tk.Label(text_col, text=hint, bg=CARD, fg=DIM, font=(FONT, -12), anchor="w", justify="left")
                        hint_label.pack(anchor="w", fill="x")
                        hint_label.bind("<Configure>", lambda e, h=hint_label: h.configure(wraplength=max(160, e.width-4)))
                    var = tk.StringVar(value=current)
                    styled_entry(row, var, width=12 if kind == "number" else 26).pack(side="right", ipady=3, padx=(12, 0))
                widgets[key] = (kind, var, item, spec)

        def save():
            values, bad = {}, []
            for key, (kind, var, item, spec) in widgets.items():
                original = item["value"]
                if kind == "bool":
                    value = original if var.get() == (original.lower() == "true") else mod_config.BOOL_VALUES[original]
                elif kind == "bool01":
                    value = "1" if var.get() else "0"
                elif kind == "slider":
                    number = float(var.get())
                    value = str(int(round(number))) if not spec.get("float") else f"{number:.3f}".rstrip("0").rstrip(".")
                else:
                    value = str(var.get()).strip()
                    if kind == "number" and not re.fullmatch(r"-?\d+(\.\d+)?", value):
                        bad.append(item["key"])
                if value != original:
                    values[key] = value
            if bad:
                return messagebox.showerror(tr("Неверное значение"), tr("Здесь нужно число: {keys}").format(keys=", ".join(bad)), parent=self)
            if not values:
                return self.scene.toast(tr("Изменений нет"))
            if schema and saves.game_running():
                return messagebox.showwarning(tr("Игра запущена"), tr("Закройте игру: Seamless Co-op читает настройки при запуске."), parent=self)
            try:
                mod_config.write(path, values)
            except OSError as exc:
                return messagebox.showerror(tr("Не удалось сохранить"), str(exc), parent=self)
            self.scene.toast(tr("Настройки сохранены: {n}").format(n=len(values)))
            self.scene.react("smug")
            back()

        self._button(window.header, tr("Сохранить"), save, 150, 42).pack(side="right")
        self._button(window.header, tr("Открыть файл"), lambda: os.startfile(path), 150, 42).pack(side="right", padx=(0, 8))
        self._button(window.header, tr("Назад"), back, 110, 42).pack(side="right", padx=(0, 8))
        self._config_widgets = widgets

    def _poll_translations(self, path, back, widgets, pending, tries):
        if getattr(self, "_config_widgets", None) is not widgets or not self.page_host.winfo_ismapped():
            return
        ready = sum(1 for text in pending if translator.cached(text) is not None)
        if ready == len(pending) or (tries <= 0 and ready):
            return self._reopen_config(path, back, widgets)
        if tries > 0:
            self.after(500, lambda: self._poll_translations(path, back, widgets, pending, tries-1))

    def _reopen_config(self, path, back, widgets):
        """Перерисовать страницу настроек после прихода переводов, не теряя ввод."""
        if not self.page_host.winfo_ismapped() or getattr(self, "_config_widgets", None) is not widgets:
            return
        values = {}
        for key, (kind, var, item, spec) in widgets.items():
            try:
                raw = var.get()
            except tk.TclError:
                continue
            if kind == "bool":
                values[key] = item["value"] if raw == (item["value"].lower() == "true") else mod_config.BOOL_VALUES[item["value"]]
            elif kind == "bool01":
                values[key] = "1" if raw else "0"
            else:
                values[key] = str(raw)
        self.open_config(path, back, values)

    def mod_settings(self, mod, back):
        """Настройки конкретного мода: его ini/toml рядом с DLL или в папке пакета.
        У модпака — все ini его DLL (по профилю автора)."""
        if profiles.is_me3_pack(mod):
            expanded = profiles.expand_pack(mod["path"], True)
            configs = [c for c in modpacks.config_files(expanded["natives"]) if c.suffix.lower() == ".ini"] \
                or modpacks.pack_configs(mod["path"])
        elif profiles.is_seamless(mod) and profiles.seamless_settings_file(mod):
            configs = [profiles.seamless_settings_file(mod)]
        elif mod.get("kind") == "native":
            # У DLL — её собственный ini; если такого нет, всё из её папки.
            configs = modpacks.dll_configs(mod["path"]) or modpacks.config_files([mod["path"]])
        else:
            configs = modpacks.config_files([mod["path"]])
        if not configs:
            return messagebox.showinfo(tr("Нет настроек"), tr("У мода «{name}» не найдено файлов настроек (ini/toml) рядом с ним.").format(name=mod["name"]), parent=self)
        if len(configs) == 1:
            return self.open_config(configs[0], back)
        window = self._open_tab(tr("Настройки мода"), mod["name"])
        self._button(window.header, tr("Назад"), back, 110, 42).pack(side="right")
        self._configs_list(window, configs, "", back=lambda: self.mod_settings(mod, back))

    def _write_appid(self, game_dir):
        try:
            profiles.ensure_steam_appid(game_dir)
            return True
        except OSError as exc:
            messagebox.showerror(tr("Нет доступа к папке игры"), tr("Не удалось создать steam_appid.txt в папке игры:\n{error}\n\nЗапустите лаунчер от имени администратора или перенесите игру в папку, куда можно писать.").format(error=exc), parent=self)
            return False

    # ── режим запуска (онлайн / офлайн) ────────────────────────────────

    def mode_label(self, profile):
        modded = profile.get("kind") in ("mods", "pack") or any(m.get("enabled", True) for m in profile.get("mods", []))
        return {"online": tr("Онлайн-серверы ME3") if modded else tr("Онлайн · EAC"),
                "offline": tr("Офлайн · без EAC"),
                "seamless": tr("Seamless Co-op · свои серверы"),
                "pack": tr("Свой загрузчик модпака")}[profiles.launch_mode(profile)]

    def set_launch_mode(self, mode, profile=None):
        p = profile or self._profile()
        if not p or profiles.launch_mode(p) in ("seamless", "pack") or profiles.launch_mode(p) == mode:
            return
        if mode == "online":
            if p.get("kind") in ("mods", "pack") or any(m.get("enabled", True) for m in p.get("mods", [])):
                self.scene.react("angry")
                if not messagebox.askyesno(tr("Онлайн с модами"), tr("Подключение к официальным серверам с модами может привести к блокировке аккаунта (мягкий бан).\n\nВключить онлайн для профиля «{name}»?").format(name=p["name"]), parent=self):
                    return
            elif p.get("game_version") and not str(p["game_version"]).startswith(("Актуальная", "Latest")):
                if not messagebox.askyesno(tr("Старая версия"), tr("Профиль «{name}» — версия {version}. Официальные серверы принимают только актуальную версию игры, поэтому в онлайне она, скорее всего, не подключится.\n\nВсё равно включить онлайн?").format(name=p["name"], version=p["game_version"]), parent=self):
                    return
        p["launch_mode"] = mode
        p["start_online"] = mode == "online"
        profiles.save(self.data)
        self.scene.toast(tr("«{name}»: {mode}").format(name=p["name"], mode=self.mode_label(p)))
        self.scene.schedule()
        self._refresh_open_page()

    def toggle_launch_mode(self):
        p = self._profile()
        if p and profiles.launch_mode(p) not in ("seamless", "pack"):
            self.set_launch_mode("offline" if profiles.launch_mode(p) == "online" else "online")

    # ── установка версий ───────────────────────────────────────────────

    def log(self, text):
        def append():
            self.logbox.insert("end", text+"\n")
            self.logbox.see("end")
            if self.log_view and self.log_view.winfo_exists():
                self.log_view.configure(state="normal")
                self.log_view.insert("end", text+"\n")
                self.log_view.see("end")
                self.log_view.configure(state="disabled")
        self.after(0, append)

    def progress(self, value, text):
        def update():
            if value is None:
                self.bar.start()
                self.status.configure(text=tr("Подготовка…"))
            else:
                self.bar.configure(mode="determinate", value=max(0,min(100,value*100)))
                self.status.configure(text=f"{value*100:.1f}%")
            self.progress_detail.configure(text=text)
        self.after(0, update)

    def ask(self, question, secret):
        """SteamCMD работает в фоновом потоке, а любое окно Tk создаём только
        в UI-потоке. Иначе Tcl/Tk выдаёт: window was deleted before its
        visibility changed."""
        answered = threading.Event()
        result = {"value": None}

        def show_dialog():
            result["value"] = simpledialog.askstring(
                "SteamCMD", question, show="*" if secret else "", parent=self
            )
            answered.set()

        self.after(0, show_dialog)
        answered.wait()
        return result["value"]

    def done(self, ok):
        def update():
            cancelled = self.stop.is_set()
            self.operation_running = False
            self.last_error = not ok and not cancelled
            self.bar.stop()
            self.bar.configure(value=100 if ok else self.bar.value)
            self.status.configure(text=tr("Готово") if ok else tr("Остановлено") if cancelled else tr("Ошибка · откройте журнал"))
            self.progress_detail.configure(text=tr("Установка завершена — добавьте папку как профиль в библиотеке") if ok
                                           else tr("Можно выбрать другую операцию"))
            if ok and getattr(self, "operation_dest", None):
                self.data.setdefault("downloads", {})[str(Path(self.operation_dest).resolve())] = self.operation_version
                profiles.save(self.data)
            self.install_button.configure(state="normal")
            self.version_button.configure(state="normal")
            self._update_install_mode()
            self.scene.react("smug" if ok else "silent" if cancelled else "dizzy", 8)
            if ok and self.state() in ("iconic", "withdrawn"):
                self.restore_from_tray()
            self.bell()
        self.after(0, update)

    def stop_download(self):
        if self.operation_running:
            self.stop.set()
            self.status.configure(text=tr("Останавливаю…"))

    def copy_log(self):
        self.clipboard_clear()
        self.clipboard_append(self.logbox.get("1.0", "end-1c"))
        self.scene.toast(tr("Журнал скопирован в буфер обмена"))

    def clear_log(self):
        self.logbox.delete("1.0", "end")
        if self.log_view and self.log_view.winfo_exists():
            self.log_view.configure(state="normal")
            self.log_view.delete("1.0", "end")
            self.log_view.configure(state="disabled")

    def choose_download_folder(self):
        dest = filedialog.askdirectory(title=tr("Выберите пустую папку для версии"), parent=self)
        if not dest: return
        self.download_path.set(dest)

    def _update_install_mode(self):
        if not hasattr(self, "install_button") or self.operation_running or self.copy_running:
            return
        steam_install = versions.install_method(self.version.get()) == "steam"
        info = versions.get(self.version.get())
        available = bool(info) and info.get("available", True)
        self.install_title.configure(text=self.tt("dock.install_title"))
        self.install_button.set_text(self.tt("dock.open_steam") if steam_install else self.tt("dock.install"))
        self.install_button.configure(state="normal" if available else "disabled")
        if not available:
            self.progress_detail.configure(text=tr("Для этой версии пока нет подтверждённых манифестов"))

    def _on_version_change(self):
        self._update_install_mode()
        self.scene.schedule()

    def start_download(self):
        if self.operation_running or self.copy_running:
            return
        version_name = self.version.get()
        version_info = versions.get(version_name)
        if not version_info:
            return messagebox.showerror(tr("Неизвестная версия"), tr("Выбранная версия отсутствует в базе лаунчера."), parent=self)
        if not version_info.get("available", True):
            return messagebox.showinfo(tr("Нужны манифесты"), tr("Для версии {version} ещё не добавлены подтверждённые манифесты SteamDB.").format(version=version_name), parent=self)
        if versions.install_method(version_name) == "steam":
            if not steam_checks.steam_running():
                return messagebox.showerror(tr("Steam не запущен"), tr("Запустите Steam, войдите в аккаунт с Elden Ring и повторите установку."), parent=self)
            if not messagebox.askyesno(tr("Актуальная версия через Steam"),
                                       tr("Актуальная версия устанавливается обычным Steam-клиентом в выбранную Steam-библиотеку.\n\nSteam проверит лицензию и доступные дополнения сам. Открыть установку Elden Ring в Steam?"),
                                       parent=self):
                return
            try:
                os.startfile("steam://install/1245620")
                self.status.configure(text=tr("Steam открыт для установки актуальной версии"))
                self.progress_detail.configure(text=tr("После установки нажмите «Добавить игру» — лаунчер найдёт её сам."))
                self.log(tr("Актуальная версия: передал установку обычному Steam-клиенту."))
            except OSError as exc:
                messagebox.showerror(tr("Не удалось открыть Steam"), tr("Откройте Steam вручную и установите Elden Ring.") + f"\n\n{exc}", parent=self)
            return
        dest = self.download_path.get().strip()
        if not dest:
            self.choose_download_folder()
            dest = self.download_path.get().strip()
            if not dest:
                return
        if not Path(dest).is_dir():
            self.download_path.set("")
            return messagebox.showerror(tr("Папка недоступна"), tr("Выбранная папка больше не существует."), parent=self)
        # Проверка места: сборки весят 55–71 ГБ.
        need = version_info.get("expected_size_bytes", 0)
        try:
            free = shutil.disk_usage(dest).free
        except OSError:
            free = None
        if need and free is not None and free < need*1.05:
            self.scene.react("dizzy")
            if not messagebox.askyesno(tr("Мало места на диске"),
                                       tr("Для версии {version} нужно около {need:.0f} ГБ, а на диске свободно {free:.0f} ГБ.\n\nЗагрузка, скорее всего, прервётся. Всё равно продолжить?").format(
                                           version=version_name, need=need/1e9, free=free/1e9), parent=self):
                return
        if any(Path(dest).iterdir()) and not messagebox.askyesno(tr("Папка не пуста"), tr("Файлы будут наложены. Продолжить?"), parent=self): return
        checks = steam_checks.status([p["path"] for p in self.data.get("profiles", [])])
        self.steam_state = checks
        if not checks["steam_running"]:
            return messagebox.showerror(tr("Steam не запущен"), tr("Запустите Steam, войдите в свой аккаунт и повторите установку."), parent=self)
        yes, no_base, no_dlc, no_pack = "✓", tr("не установлена локально"), tr("не найдена локально"), tr("не найден локально")
        self.log(tr("Проверка Steam:") + f" Steam {yes} | Elden Ring {yes if checks['base_installed'] else no_base} | "
                 f"Shadow of the Erdtree {yes if checks['erdtree_installed'] else no_dlc} | "
                 f"Tarnished Pack {yes if checks['tarnished_installed'] else no_pack}")
        self.log(tr(checks["license_note"]))
        if not messagebox.askyesno(tr("Вход через SteamCMD"),
                                   tr("SteamCMD потребует вход в аккаунт с Elden Ring и может временно вывести обычный клиент Steam из сети.\n\nОткроется отдельное окно: введите пароль только в SteamCMD и подтвердите Steam Guard. Лаунчер не читает и не сохраняет пароль или код.\n\nПродолжить?"),
                                   parent=self):
            return
        self.operation_running = True
        self.operation_version = version_name
        self.operation_dest = dest
        self.last_error = False
        self.install_button.configure(state="disabled")
        self.install_button.set_text(self.tt("dock.installing"))
        self.version_button.configure(state="disabled")
        self.stop = threading.Event()
        self.bar.configure(mode="indeterminate", value=0)
        self.bar.set_text(tr("Подготовка SteamCMD…"))
        self.bar.start(12)
        self.install_title.configure(text=f"{self.tt('dock.install_title')} · {version_name}")
        self.status.configure(text=tr("Подготовка…"))
        self.progress_detail.configure(text=tr("Подключаюсь к SteamCMD…"))
        try:
            steam_download.download(version_name, dest, self.log, self.progress, self.ask, self.done, self.stop)
        except Exception as exc:
            self.log(str(exc))
            self.done(False)

    def show_log(self):
        set_active_tab(self,"log")
        window = self._open_tab(self.tt("page.log"), tr("Операция продолжается при смене разделов"))
        actions = tk.Frame(window, bg=PAGE_BG)
        actions.pack(fill="x", side="bottom", padx=20, pady=(0, 16))
        self._button(actions, tr("Копировать"), self.copy_log, 150, 44).pack(side="left", padx=(0, 8))
        self._button(actions, tr("Очистить"), self.clear_log, 130, 44).pack(side="left", padx=(0, 8))
        self._button(actions, tr("Журнал ошибок"), lambda: os.startfile(crash_log.log_path()) if crash_log.log_path().exists()
                     else self.scene.toast(tr("Ошибок пока не было")), 170, 44).pack(side="left", padx=(0, 8))
        self._button(actions, tr("Папка данных"), self.open_data_folder, 160, 44).pack(side="left")
        tk.Label(actions, text=tr("Не публикуйте пароли и коды Steam Guard"), bg=PAGE_BG, fg=DIM,
                 font=(FONT, -12)).pack(side="right")
        box = tk.Frame(window, bg="#11100d", highlightthickness=1, highlightbackground=CARD_BORDER)
        box.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        scroll = ttk.Scrollbar(box, orient="vertical")
        scroll.pack(side="right", fill="y")
        self.log_view = tk.Text(box, bg="#11100d", fg=TEXT, font=("Consolas", -14), wrap="word", relief="flat",
                                padx=16, pady=12, yscrollcommand=scroll.set, borderwidth=0,
                                selectbackground="#4a3c20", selectforeground="#fff5d3", insertbackground=GOLD)
        scroll.configure(command=self.log_view.yview)
        self.log_view.pack(fill="both", expand=True)
        content = self.logbox.get("1.0", "end-1c")
        self.log_view.insert("end", content if content.strip() else tr("Журнал пуст. Здесь появятся сообщения установки и запусков.") + "\n")
        self.log_view.see("end")
        self.log_view.configure(state="disabled")

    def repair_profile(self):
        p = self._profile()
        if not p:
            return self.add_vanilla()
        path = filedialog.askdirectory(title=tr("Укажите папку игры для выбранного профиля"), parent=self)
        if not path:
            return
        if not profiles.game_exe(path).is_file():
            return messagebox.showerror(tr("Игра не найдена"), tr("В папке нет eldenring.exe"), parent=self)
        p["path"] = str(profiles.game_exe(path).parent)
        profiles.save(self.data)
        self.refresh()
        self._refresh_open_page()

    def show_profile_menu(self,event=None):
        if not self._profile():
            return self.show_library()
        p = self._profile()
        menu = tk.Menu(self,tearoff=False,bg=PANEL,fg=TEXT,activebackground="#443b2d",activeforeground=GOLD,font=(FONT,-16))
        groups = (
            ((tr("Играть"), self.launch), (tr("Открыть папку"), self.open_folder)),
            ((tr("Модпак и его настройки") if p.get("kind") == "pack" else tr("Моды и Seamless Co-op"), self.manage_mods),
             (tr("Импортировать модпак…"), self.import_modpack),
             (tr("Профиль из файла .me3…"), self.import_me3_file),
             (tr("Создать копию для модов"), self.create_mod)),
            ((tr("Сменить обложку…"), self.change_cover),) + (((tr("Убрать обложку"), self.remove_cover),) if p.get("cover") else ()),
            ((tr("Переименовать"), self.rename_profile), (tr("Исправить путь"), self.repair_profile),
             (tr("Показать журнал"), self.show_log)),
            ((tr("Удалить запись"), self.delete_profile),),
        )
        for i, group in enumerate(groups):
            if i:
                menu.add_separator()
            for text, action in group:
                menu.add_command(label=text, command=action)
            if i == 0 and profiles.launch_mode(p) not in ("seamless", "pack"):
                # Режим запуска: офлайн без EAC или онлайн — отдельно для каждого профиля.
                modes = tk.Menu(menu, tearoff=False, bg=PANEL, fg=TEXT, activebackground="#443b2d",
                                activeforeground=GOLD, selectcolor=GOLD, font=(FONT, -16))
                current = tk.StringVar(value=profiles.launch_mode(p))
                menu._mode_var = current  # держим ссылку, пока меню открыто
                modes.add_radiobutton(label=tr("Офлайн · без EAC (рекомендуется)"), variable=current, value="offline",
                                      command=lambda: self.set_launch_mode("offline"))
                modded = p.get("kind") in ("mods", "pack") or any(m.get("enabled", True) for m in p.get("mods", []))
                modes.add_radiobutton(label=tr("Онлайн-серверы ME3 (риск бана)") if modded else tr("Онлайн · EAC"),
                                      variable=current, value="online", command=lambda: self.set_launch_mode("online"))
                menu.add_cascade(label=tr("Режим запуска: {mode}").format(mode=self.mode_label(p)), menu=modes)
            exe = profiles.game_exe(p["path"])
            if i == 0 and exe.is_file() and profiles.foreign_loaders(exe.parent):
                loaders = tk.Menu(menu, tearoff=False, bg=PANEL, fg=TEXT, activebackground="#443b2d",
                                  activeforeground=GOLD, selectcolor=GOLD, font=(FONT, -16))
                choice = tk.StringVar(value=p.get("foreign_loaders", ""))
                menu._loader_var = choice
                loaders.add_radiobutton(label=tr("Отключать на время игры (рекомендуется)"), variable=choice,
                                        value="disable", command=lambda: self.set_loader_choice("disable"))
                loaders.add_radiobutton(label=tr("Загружать вместе с игрой"), variable=choice,
                                        value="keep", command=lambda: self.set_loader_choice("keep"))
                menu.add_cascade(label=tr("Сторонние загрузчики (dinput8 и др.)"), menu=loaders)
        x = event.x_root if event else self.winfo_pointerx()
        y = event.y_root if event else self.winfo_pointery()
        try:
            menu.tk_popup(x,y)
        finally:
            menu.grab_release()

    def request_close(self):
        if self.copy_running:
            messagebox.showinfo(tr("Копирование профиля"), tr("Дождитесь завершения копирования перед закрытием лаунчера."), parent=self)
            return
        if self.operation_running:
            if messagebox.askyesno(tr("Идёт установка"), tr("Остановить установку и закрыть лаунчер после завершения остановки?"), parent=self):
                self.stop_download()
                self._wait_close()
            return
        self._save_geometry()
        self.destroy()

    def _wait_close(self):
        if self.operation_running:
            self.after(150,self._wait_close)
        else:
            self._save_geometry()
            self.destroy()

    def destroy(self):
        self.tray.hide()
        if hasattr(self,"background_controller"):
            self.background_controller.close()
        super().destroy()


def run():
    Launcher().mainloop()


if __name__ == "__main__":
    run()

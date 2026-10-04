"""Verified Figma colours and desktop sizing; values are logical pixels."""
FONT = "El Messiri"
BG = "#0b0b0a"
PANEL = "#1d1b18"
GOLD = "#ffdd99"
TEXT = "#ffead3"
MUTED = "#988d7a"
BORDER = "#817662"
SELECTED = "#e2d6c0"
SPACE = (4, 8, 12, 16, 24, 32, 48, 64)
NAV_HEIGHT = 64
DOCK_HEIGHT = 148

# Страницы-вкладки (Библиотека, Моды, Настройки, Журнал) — единая палитра,
# чтобы заголовки, карточки и кнопки не давали «заплаток» разного цвета.
PAGE_BG = "#16140f"
CARD = "#1f1c17"
CARD_HOVER = "#26221b"
CARD_SELECTED = "#2f281c"
CARD_BORDER = "#3a3328"
INK = "#f1e6cf"
DIM = "#8f8570"
OK = "#a9c47f"
WARN = "#d9925f"
OFF = "#5c5547"

# Слой локализации: переключатель RU/EN в навигации переключает всё, что
# рисуется в сцене (навигация, главная, нижняя панель) и заголовки вкладок.
# FAQ и системные диалоги пока только на русском.
STRINGS = {
    "nav.home": {"ru": "ОСНОВНОЕ", "en": "HOME"},
    "nav.library": {"ru": "БИБЛИОТЕКА", "en": "LIBRARY"},
    "nav.mods": {"ru": "МОДЫ", "en": "MODS"},
    "nav.faq": {"ru": "FAQ", "en": "FAQ"},
    "nav.settings": {"ru": "НАСТРОЙКИ", "en": "SETTINGS"},
    "nav.saves": {"ru": "СОХРАНЕНИЯ", "en": "SAVES"},
    "page.saves": {"ru": "Сохранения", "en": "Saves"},
    "home.playtime": {"ru": "в игре", "en": "played"},
    "nav.steam": {"ru": "STEAM", "en": "STEAM"},
    "nav.game": {"ru": "ИГРА", "en": "GAME"},
    "nav.dlc": {"ru": "DLC", "en": "DLC"},
    "dock.version_label": {"ru": "ВЕРСИЯ ДЛЯ УСТАНОВКИ", "en": "VERSION TO INSTALL"},
    "dock.install": {"ru": "Установить", "en": "Install"},
    "dock.open_steam": {"ru": "Открыть Steam", "en": "Open Steam"},
    "dock.installing": {"ru": "Установка…", "en": "Installing…"},
    "dock.install_title": {"ru": "УСТАНОВКА", "en": "INSTALLATION"},
    "dock.current": {"ru": "Актуальная · Steam", "en": "Latest · Steam"},
    "dock.ready": {"ru": "Готово", "en": "Ready"},
    "dock.stop": {"ru": "Стоп", "en": "Stop"},
    "dock.log": {"ru": "Журнал", "en": "Log"},
    "home.library_title": {"ru": "ВАША БИБЛИОТЕКА", "en": "YOUR LIBRARY"},
    "home.profile_title": {"ru": "ВЫБРАННЫЙ ПРОФИЛЬ", "en": "SELECTED PROFILE"},
    "home.empty_name": {"ru": "Между мирами", "en": "Between the worlds"},
    "home.empty_detail": {"ru": "Добавьте установленную игру — лаунчер сам поищет её в Steam — или выберите версию для установки внизу.",
                          "en": "Add an installed copy — the launcher will look for it in Steam — or pick a version to install below."},
    "home.add_game": {"ru": "Добавить игру", "en": "Add game"},
    "home.play": {"ru": "Играть", "en": "Play"},
    "home.fix_path": {"ru": "Указать папку", "en": "Locate game"},
    "home.actions": {"ru": "Действия профиля", "en": "Profile actions"},
    "home.open_library": {"ru": "Открыть библиотеку", "en": "Open library"},
    "home.ready": {"ru": "Готов к запуску", "en": "Ready to play"},
    "home.missing": {"ru": "Папка игры недоступна", "en": "Game folder not found"},
    "home.mods_active": {"ru": "активных модов", "en": "active mods"},
    "home.last_played": {"ru": "запуск", "en": "last played"},
    "kind.vanilla": {"ru": "Ваниль", "en": "Vanilla"},
    "kind.mods": {"ru": "Мод-профиль", "en": "Modded"},
    "kind.seamless": {"ru": "Seamless Co-op", "en": "Seamless Co-op"},
    "kind.other": {"ru": "Профиль", "en": "Profile"},
    "kind.pack": {"ru": "Модпак", "en": "Modpack"},
    "page.library": {"ru": "Библиотека", "en": "Library"},
    "page.mods": {"ru": "Моды", "en": "Mods"},
    "page.settings": {"ru": "Настройки", "en": "Settings"},
    "page.log": {"ru": "Журнал операций", "en": "Operation log"},
}


def t(lang, key, default=None):
    entry = STRINGS.get(key)
    if not entry:
        return default if default is not None else key
    return entry.get(lang, entry.get("ru", key))

# FAQ-диалог с проводником. Поля: вопрос, подзаголовок, ответ, подпись
# действия, цель действия, иконка (alert/chat/exit → dialogs/glyph-*.png).
# Цели: home, library, mods, settings, log, add_game, discord.
FAQ = (
    ("Кто ты такой?", "Знакомство",
     "Я — IWaithI, проводник этого лаунчера. Он хранит ваши установки Elden Ring, держит моды отдельно "
     "от чистой игры и умеет откатывать патчи через SteamCMD. Файлов игры здесь нет — только пути, "
     "настройки и немного моей болтовни.", "Открыть библиотеку", "library", "chat"),
    ("С чего начать?", "Первые шаги",
     "Нажмите «Добавить игру» — я сам обыщу ваши Steam-библиотеки. Не нашёл? Укажите папку Game "
     "с eldenring.exe вручную. Дальше выбираете профиль и жмёте «Играть». Проще, чем пройти Маргита, обещаю.",
     "Добавить игру", "add_game", "alert"),
    ("Как откатиться на старый патч?", "Установка версий",
     "Выберите версию в нижней панели, нажмите «Установить» и укажите пустую папку. SteamCMD попросит "
     "войти в аккаунт с игрой — пароль и Steam Guard вводятся только в его окне, я их не вижу. "
     "Прогресс виден из любого раздела.", "К установке", "home", "alert"),
    ("Как поставить моды?", "Mod Engine 3",
     "Сначала создайте копию игры для модов — ваниль останется чистой. Во вкладке «Моды» добавьте папки "
     "пакетов или DLL, расставьте порядок стрелками и укажите me3.exe. Двойной щелчок по моду включает "
     "или выключает его.", "Открыть моды", "mods", "alert"),
    ("Хочу играть с друзьями", "Seamless Co-op",
     "Во вкладке «Моды» нажмите «Подключить» в строке Seamless Co-op — он загрузится вместе с остальными "
     "модами этого же профиля. Пароль сессии и сложность — там же, кнопка «Настройки». Главное, чтобы "
     "версия мода у всей компании совпадала.", "Открыть моды", "mods", "chat"),
    ("Меня не забанят?", "Онлайн и безопасность",
     "Старые патчи и моды — только офлайн. Режим выбирается для каждого профиля: плашка под путём на главной "
     "или «Режим запуска» в меню профиля. Офлайн запускает игру без Easy Anti-Cheat и серверов — так безопасно. "
     "Пароли я не читаю и не храню.", "Настроить моды", "mods", "alert"),
    ("Что-то сломалось", "Диагностика",
     "Без паники, Погасший. Точки в левом верхнем углу покажут, запущен ли Steam. Игра не стартует — "
     "«Исправить путь» в меню профиля. Установка упала — откройте журнал, скопируйте его и пришлите автору.",
     "Открыть журнал", "log", "alert"),
    ("Чьё это всё?", "Права и авторство",
     "Это неофициальный фан-проект: он не связан с FromSoftware и Bandai Namco. Мой арт принадлежит автору "
     "лаунчера. Фоны — ваши скриншоты из Steam, а если их нет — изображения из открытых источников в интернете.",
     "О программе", "settings", "chat"),
    ("Связаться с автором", "Discord",
     "Нашли баг или есть идея? Пишите автору в Discord: iwaithi. Приложите журнал операций — так "
     "разберёмся быстрее. И никогда не присылайте пароли или коды Steam Guard, даже мне.",
     "Скопировать тег iwaithi", "discord", "chat"),
    ("Мне ничего не надо", "До встречи, Погасший",
     "Тогда ступайте, и да направит вас благодать. Если понадоблюсь — я здесь, во вкладке FAQ. "
     "Или просто нажмите F1.", "На основной экран", "home", "exit"),
)

# Реплика при открытии FAQ — выбирается случайно, пока вопрос не выбран.
FAQ_GREETINGS = (
    "А, Погасший! Выбирайте вопрос слева — расскажу всё, что знаю.",
    "Снова вы? Благодать привела вас в правильное место. Спрашивайте.",
    "Не стойте у костра молча — выберите вопрос, я отвечу.",
    "Добро пожаловать. Клавиши 1–9 тоже работают, если лень тянуться к мыши.",
)

# Поза ассистента для каждого вопроса (по порядку FAQ) — файлы characters/chibi/<поза>.png.
FAQ_POSES = ("talk", "smug", "confused", "read", "drink", "angry", "dizzy", "silent", "peek", "bonfire")

# Реплики при щелчке по ассистенту.
ASSISTANT_QUIPS = {
    "ru": (
        ("talk", "Эй! Я не кнопка. Хотя… ладно, немного кнопка."),
        ("smug", "Если что, я знаю, где лежат все ваши сохранения."),
        ("drink", "Перерыв. Даже Погасшим нужен чай."),
        ("read", "Читаю патчноуты. Опять понерфили что-то любимое."),
        ("confused", "Карта Междуземья перевёрнута? Ничего, я тоже не сразу нашёл Лейнделл."),
        ("angry", "Ещё раз ткнёшь — позову Малению."),
        ("silent", "…"),
        ("peek", "Я тут. Я всегда тут."),
    ),
    "en": (
        ("talk", "Hey! I'm not a button. Well… maybe a little."),
        ("smug", "Just so you know, I remember where all your saves are."),
        ("drink", "Break time. Even the Tarnished need tea."),
        ("read", "Reading patch notes. They nerfed something good again."),
        ("confused", "Map upside down? Don't worry, I got lost on the way to Leyndell too."),
        ("angry", "Poke me again and I'm calling Malenia."),
        ("silent", "…"),
        ("peek", "I'm here. I'm always here."),
    ),
}

FAQ_EN = (
    ("Who are you?", "Introductions",
     "I'm IWaithI, this launcher's guide. It keeps your Elden Ring installs, keeps mods away from the clean game "
     "and can roll back patches through SteamCMD. There are no game files here — just paths, settings and a bit "
     "of my chatter.", "Open library", "library", "chat"),
    ("Where do I start?", "First steps",
     "Press «Add game» — I'll search your Steam libraries myself. Didn't find it? Point me to the Game folder with "
     "eldenring.exe. Then pick a profile and press «Play». Easier than Margit, I promise.",
     "Add game", "add_game", "alert"),
    ("How do I roll back a patch?", "Installing versions",
     "Pick a version in the bottom panel, press «Install» and choose an empty folder. SteamCMD will ask you to "
     "sign in to the account that owns the game — the password and Steam Guard go only into its window, I never "
     "see them. Progress is visible from any tab.", "To installation", "home", "alert"),
    ("How do I install mods?", "Mod Engine 3",
     "First make a copy of the game for mods — vanilla stays clean. In the «Mods» tab add package folders or DLLs, "
     "set the order with the arrows and point to me3.exe. Double-click a mod to switch it on or off.",
     "Open mods", "mods", "alert"),
    ("I want to play with friends", "Seamless Co-op",
     "In the «Mods» tab press «Connect» on the Seamless Co-op row — it loads together with the other mods of the "
     "same profile. Session password and difficulty are right there under «Settings». Just make sure everyone has "
     "the same mod version.", "Open mods", "mods", "chat"),
    ("Will I get banned?", "Online and safety",
     "Old patches and mods — offline only. The mode is set per profile: the pill under the path on the home screen "
     "or «Launch mode» in the profile menu. Offline starts the game without Easy Anti-Cheat or servers — that's safe. "
     "I never read or store passwords.",
     "Mod settings", "mods", "alert"),
    ("Something broke", "Troubleshooting",
     "Don't panic, Tarnished. The dots in the top-left corner show whether Steam is running. The game won't start — "
     "«Fix path» in the profile menu. An install failed — open the log, copy it and send it to the author.",
     "Open log", "log", "alert"),
    ("Who owns all this?", "Rights and credits",
     "This is an unofficial fan project, not affiliated with FromSoftware or Bandai Namco. My art belongs to the "
     "launcher's author. Backgrounds are your Steam screenshots, or images from open sources on the internet if you have none.",
     "About", "settings", "chat"),
    ("Contact the author", "Discord",
     "Found a bug or have an idea? Message the author on Discord: iwaithi. Attach the operation log — it speeds "
     "things up. And never send passwords or Steam Guard codes, not even to me.",
     "Copy tag iwaithi", "discord", "chat"),
    ("I don't need anything", "Farewell, Tarnished",
     "Then go forth, and may grace guide you. If you need me, I'm here in the FAQ tab. Or just press F1.",
     "To home screen", "home", "exit"),
)

FAQ_GREETINGS_EN = (
    "Ah, Tarnished! Pick a question on the left — I'll tell you everything I know.",
    "You again? Grace has led you to the right place. Ask away.",
    "Don't just stand by the bonfire — pick a question and I'll answer.",
    "Welcome. Keys 1–9 work too, if reaching for the mouse is too much.",
)

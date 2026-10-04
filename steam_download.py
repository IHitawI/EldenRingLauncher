import os
import queue
import re
import shutil
import subprocess
import threading
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path
try:
    import winreg
except ImportError:  # позволяет хотя бы открыть проект вне Windows
    winreg = None

from profiles import data_dir, user_dir
from versions import APP_ID, get
from i18n import tr

STEAMCMD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"


def _eta(seconds: float) -> str:
    """Короткое отображение примерного времени до конца загрузки."""
    if seconds <= 0 or seconds == float("inf"):
        return tr("вычисляю…")
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return tr("{h} ч {m:02d} мин").format(h=hours, m=minutes)
    return tr("{m} мин {s:02d} с").format(m=minutes, s=seconds)

def active_steam_username() -> str | None:
    """Имя последнего активного Steam-профиля. Пароль не читаем и не храним."""
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            value, _ = winreg.QueryValueEx(key, "AutoLoginUser")
        return value.strip() or None
    except OSError:
        return None


def _steamcmd() -> Path:
    folder = user_dir() / "steamcmd"
    exe = folder / "steamcmd.exe"
    if exe.is_file():
        return exe
    folder.mkdir(exist_ok=True)
    archive = folder / "steamcmd.zip"
    try:
        urllib.request.urlretrieve(STEAMCMD_URL, archive)
        with zipfile.ZipFile(archive) as package:
            package.extractall(folder)
    except Exception as exc:
        raise RuntimeError(tr("Не удалось скачать SteamCMD: {error}").format(error=exc)) from exc
    finally:
        archive.unlink(missing_ok=True)
    if not exe.is_file():
        raise RuntimeError(tr("SteamCMD не найден после распаковки"))
    return exe


def _workspace_steamcmd(destination: Path) -> Path:
    """SteamCMD хранит content-кэш рядом с собственным exe. Копируем его
    рабочие файлы в выбранный диск, исключая старый кэш депо, чтобы C: не
    использовался для десятков гигабайт временных файлов."""
    source_exe = _steamcmd()
    # Соседняя папка на том же диске: junction на destination не зацикливается
    # через собственную служебную папку SteamCMD.
    workspace = destination.parent / f".steamcmd-work-{uuid.uuid4().hex[:8]}"
    workspace_exe = workspace / "steamcmd.exe"
    if not workspace_exe.is_file():
        shutil.copytree(source_exe.parent, workspace, ignore=shutil.ignore_patterns("steamapps"), dirs_exist_ok=True)
    return workspace_exe


def _redirect_depots_to_target(workspace: Path, depots, destination: Path) -> None:
    """SteamCMD фиксированно пишет в steamapps/content/.../depot_ID. Создаём
    для каждого depot_ID NTFS junction на выбранную папку: SteamCMD продолжает
    качать обычным последовательным способом, но файлы физически создаются
    сразу в назначении пользователя.
    """
    cache_root = workspace / "steamapps" / "content" / f"app_{APP_ID}"
    cache_root.mkdir(parents=True, exist_ok=True)
    for depot, _manifest in depots:
        junction = cache_root / f"depot_{depot}"
        if junction.exists() or junction.is_symlink():
            raise RuntimeError(tr("Служебный путь уже существует: {path}").format(path=junction))
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(destination)],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            raise RuntimeError(tr("Не удалось создать связь для депо {depot}: {error}").format(depot=depot, error=result.stderr.strip() or result.stdout.strip()))


def _reader(stream, output):
    try:
        for line in iter(stream.readline, ""):
            output.put(line.rstrip())
    finally:
        output.put(None)


def _save_diagnostics(workspace: Path) -> Path | None:
    """Сохраняет служебный stderr SteamCMD рядом с лаунчером.

    Это не содержит пароль или код Steam Guard, но помогает понять, был ли
    заблокирован апдейтер/сеть SteamCMD.
    """
    source = workspace / "logs" / "stderr.txt"
    if not source.is_file() or source.stat().st_size == 0:
        return None
    target_dir = data_dir()
    target = target_dir / "steamcmd-last-error.txt"
    try:
        shutil.copy2(source, target)
        return target
    except OSError:
        return None


def _cleanup_workspace(workspace: Path, depots) -> None:
    """Удаляет только временный SteamCMD-каталог, не трогая выбранную игру."""
    cache_root = workspace / "steamapps" / "content" / f"app_{APP_ID}"
    for depot, _manifest in depots:
        junction = cache_root / f"depot_{depot}"
        if junction.exists() or junction.is_symlink():
            subprocess.run(
                ["cmd", "/c", "rmdir", str(junction)],
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    shutil.rmtree(workspace, ignore_errors=True)


def _auth_command_file(workspace: Path, exe: Path, username: str) -> Path:
    """Создаёт одноразовый cmd-файл для наглядной ошибки входа.

    SteamCMD не отдаёт интерактивный пароль через pipe. Поэтому при удачном
    входе окно закрывается само, а при ошибке остаётся на экране до нажатия
    клавиши — пользователь может прочесть действительную причину.
    """
    script = workspace / "show-auth-error.cmd"
    command = subprocess.list2cmdline([str(exe), "+login", username, "+quit"])
    script.write_text(
        "@echo off\r\n"
        f"{command}\r\n"
        "set steamcmd_code=%errorlevel%\r\n"
        "if not \"%steamcmd_code%\"==\"0\" if not \"%steamcmd_code%\"==\"7\" (\r\n"
        "  echo.\r\n"
        "  echo SteamCMD failed. Copy the error above before pressing any key.\r\n"
        "  pause\r\n"
        ")\r\n"
        "exit /b %steamcmd_code%\r\n",
        encoding="utf-8",
    )
    return script


def _folder_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def _move_finished_depots(cache_root: Path, depots, destination: Path, log, stop) -> bool:
    """SteamCMD складывает download_depot в собственный content-кэш. После
    успешного завершения переносим (не дублируем) файлы в папку пользователя.
    На одном диске os.replace — это быстрый перенос, между дисками — копия с
    удалением исходника.
    """
    destination.mkdir(parents=True, exist_ok=True)
    for depot, _manifest in depots:
        source = cache_root / f"depot_{depot}"
        if not source.is_dir():
            raise RuntimeError(tr("Не найден завершённый кэш депо {depot}").format(depot=depot))
        log(tr("Переношу депо {depot} в выбранную папку…").format(depot=depot))
        for root, _dirs, files in os.walk(source):
            if stop.is_set():
                return False
            relative = Path(root).relative_to(source)
            target_dir = destination / relative
            target_dir.mkdir(parents=True, exist_ok=True)
            for name in files:
                if stop.is_set():
                    return False
                old_file = Path(root) / name
                new_file = target_dir / name
                try:
                    os.replace(old_file, new_file)
                except OSError:
                    shutil.copy2(old_file, new_file)
                    old_file.unlink()
    return True


def download(version_name, destination, log, progress, _prompt, finished, stop):
    """Запускается из GUI в отдельном потоке.

    SteamCMD работает в отдельной консоли: он скачивает депо последовательно
    и запрашивает пароль/Steam Guard штатно. Лаунчер секреты не читает и не
    хранит.
    """
    def run():
        workspace = None
        success = False
        depots = []
        try:
            version = get(version_name)
            if not version:
                raise RuntimeError(tr("Версия отсутствует в versions.py"))
            if not version.get("available", True):
                raise RuntimeError(tr("Для этой версии ещё не добавлены подтверждённые манифесты SteamDB."))
            if version.get("install_method") == "steam":
                raise RuntimeError(tr("Актуальная версия должна устанавливаться через обычный Steam-клиент."))
            depots = list(version["depots"]) + list(version.get("dlc_depots", []))
            username = active_steam_username()
            if not username:
                raise RuntimeError(tr("Steam-профиль не найден. Запустите Steam, войдите в аккаунт и перезапустите лаунчер."))
            log(tr("Использую Steam-профиль: {name}").format(name=username))
            destination_path = Path(destination)
            destination_path.mkdir(parents=True, exist_ok=True)
            exe = _workspace_steamcmd(destination_path)
            workspace = exe.parent
            _redirect_depots_to_target(exe.parent, depots, destination_path)
            log(tr("Открываю SteamCMD только для входа. Введите пароль и подтвердите Steam Guard в этом окне."))
            auth_script = _auth_command_file(exe.parent, exe, username)
            auth = subprocess.Popen(
                ["cmd", "/d", "/c", str(auth_script)],
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
            while auth.poll() is None:
                if stop.is_set():
                    auth.kill(); auth.wait(); log(tr("Авторизация остановлена.")); return
                time.sleep(0.5)
            # SteamCMD for Windows иногда возвращает 7 даже после успешного
            # `Logging in ... OK` и `Waiting for user info... OK` (обычно
            # после собственного обновления). Для нашего одноразового входа
            # это не повод отменять следующий download_depot: его авторизация
            # уже сохранена во временном workspace.
            if auth.returncode not in (0, 7):
                diagnostic = _save_diagnostics(exe.parent)
                detail = tr("SteamCMD не смог завершить вход (код {code}). Проверьте текст в открывшемся окне SteamCMD: часто это сеть или обновление SteamCMD, а не неверный пароль.").format(code=auth.returncode)
                if diagnostic:
                    detail += " " + tr("Диагностика сохранена: {path}").format(path=diagnostic)
                raise RuntimeError(detail)
            log(tr("Вход выполнен. Загрузка SteamCMD запущена скрыто; вывод появится в журнале."))
            cmd = [str(exe), "+@ShutdownOnFailedCommand", "1", "+@NoPromptForPassword", "0",
                   "+force_install_dir", str(destination_path), "+login", username]
            for depot, manifest in depots:
                cmd += ["+download_depot", APP_ID, depot, manifest]
            cmd += ["+quit"]
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            output = queue.Queue()
            threading.Thread(target=_reader, args=(proc.stdout, output), daemon=True).start()
            depot_index = {depot: index for index, (depot, _manifest) in enumerate(depots, start=1)}
            active_depot = None
            expected_bytes = None
            initial_bytes = _folder_size(destination_path)
            expected_total_bytes = version.get("expected_size_bytes")
            start_bytes = initial_bytes
            previous_bytes, previous_time = initial_bytes, time.monotonic()
            last_progress = 0.0
            while proc.poll() is None:
                if stop.is_set():
                    proc.kill(); proc.wait(); log(tr("Загрузка остановлена.")); return
                try:
                    line = output.get(timeout=0.5)
                except queue.Empty:
                    line = None
                if line:
                    # При скрытом запуске SteamCMD почти всегда отдаёт лишь
                    # эту служебную шапку; она не помогает пользователю.
                    is_banner = (
                        line.startswith("Steam Console Client")
                        or line.startswith("-- type 'quit'")
                        or line.startswith("\\-- type 'quit'")
                        or line.startswith("Loading Steam API")
                        or line.startswith('"@')
                    )
                    if not is_banner:
                        log(line)
                    match = re.search(r"Downloading depot (\d+) \([^,]+,\s*(\d+)\s*MB\)", line, re.I)
                    if match:
                        active_depot = match.group(1)
                        expected_bytes = int(match.group(2)) * 1024 * 1024
                        start_bytes = _folder_size(destination_path)
                        previous_bytes, previous_time = start_bytes, time.monotonic()
                now = time.monotonic()
                if now - last_progress >= 1.0:
                    current_bytes = _folder_size(destination_path)
                    elapsed = max(now - previous_time, 0.001)
                    speed = max(0, current_bytes - previous_bytes) / elapsed / (1024 * 1024)
                    downloaded_bytes = max(0, current_bytes - initial_bytes)
                    downloaded_gib = downloaded_bytes / (1024 ** 3)
                    if expected_total_bytes:
                        overall = min(0.995, downloaded_bytes / expected_total_bytes)
                        total_gib = expected_total_bytes / (1024 ** 3)
                        remaining = max(0, expected_total_bytes - downloaded_bytes)
                        eta = _eta(remaining / (speed * 1024 * 1024)) if speed >= 0.05 else tr("вычисляю…")
                        progress(
                            overall,
                            tr("Скачано {done:.2f} из {total:.2f} ГиБ, {speed:.1f} МБ/с, осталось ~{eta}").format(done=downloaded_gib, total=total_gib, speed=speed, eta=eta),
                        )
                    elif active_depot:
                        current = max(0, current_bytes - start_bytes)
                        ratio = min(0.99, current / expected_bytes) if expected_bytes else 0.0
                        index = depot_index.get(active_depot, 1)
                        overall = ((index - 1) + ratio) / len(depots)
                        progress(overall, tr("Депо {index}/{count}: {mb:.0f} МБ, {speed:.1f} МБ/с").format(index=index, count=len(depots), mb=current / (1024 * 1024), speed=speed))
                    else:
                        progress(None, tr("Загружено {done:.2f} ГиБ, скорость {speed:.1f} МБ/с").format(done=downloaded_gib, speed=speed))
                    previous_bytes, previous_time, last_progress = current_bytes, now, now
            if proc.returncode != 0:
                raise RuntimeError(tr("SteamCMD завершился с кодом {code}").format(code=proc.returncode))
            progress(1.0, tr("Готово"))
            success = True
        except Exception as exc:
            log(tr("Ошибка: {error}").format(error=exc))
        finally:
            try:
                if workspace is not None:
                    _cleanup_workspace(workspace, depots)
                    log(tr("Временные данные SteamCMD очищены; выбранные файлы игры не затронуты."))
            except Exception as exc:
                log(tr("Не удалось очистить временные данные SteamCMD: {error}").format(error=exc))
                success = False
            finally:
                finished(success)
    threading.Thread(target=run, daemon=True).start()

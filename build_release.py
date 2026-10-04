"""Сборка релиза: EXE через PyInstaller + zip для публикации.

    py build_release.py

Результат: release/EldenRingLauncher-v<версия>.zip — внутри только
EldenRingLauncher.exe и _internal (без data, backups, steamcmd и исходников).
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import app_info

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
RELEASE = ROOT / "release"


def version_file():
    parts = [int(p) for p in app_info.VERSION.split(".")] + [0] * 4
    numbers = tuple(parts[:4])
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{app_info.AUTHOR}'),
      StringStruct('FileDescription', '{app_info.APP_NAME}'),
      StringStruct('FileVersion', '{app_info.VERSION}'),
      StringStruct('InternalName', 'EldenRingLauncher'),
      StringStruct('LegalCopyright', 'Unofficial fan project. Not affiliated with FromSoftware or Bandai Namco.'),
      StringStruct('OriginalFilename', 'EldenRingLauncher.exe'),
      StringStruct('ProductName', '{app_info.APP_NAME}'),
      StringStruct('ProductVersion', '{app_info.VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    (ROOT / "version_info.txt").write_text(text, encoding="utf-8")


def main():
    version_file()
    subprocess.run([sys.executable, "-m", "PyInstaller", "EldenRingLauncher.spec", "--noconfirm",
                    "--distpath", str(DIST), "--workpath", str(BUILD)], cwd=ROOT, check=True)
    folder = DIST / "EldenRingLauncher"
    RELEASE.mkdir(exist_ok=True)
    archive = RELEASE / f"EldenRingLauncher-v{app_info.VERSION}.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in folder.rglob("*"):
            if path.is_file():
                zf.write(path, Path("EldenRingLauncher") / path.relative_to(folder))
    print(f"\nГотово: {archive} ({archive.stat().st_size / 2**20:.1f} МБ)")


if __name__ == "__main__":
    main()

# -*- mode: python ; coding: utf-8 -*-
# Сборка: py build_release.py (он же создаёт version_info.txt и zip для релиза).
from PyInstaller.utils.hooks import collect_all

# В сборку попадает только assets/ (интерфейс, фоны, шрифт, иконка).
# Исходники макетов лежат в design_source/ и не включаются.
datas = [('assets', 'assets')]
binaries = []
hiddenimports = ['tkinter', '_tkinter', 'pystray._win32']
tmp_ret = collect_all('tkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['splash.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EldenRingLauncher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX выключен: сжатые им EXE заметно чаще ловят ложные срабатывания антивирусов.
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
    version='version_info.txt',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='EldenRingLauncher',
)

# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('openpyxl')
hiddenimports += collect_submodules('pypdf')
hiddenimports += collect_submodules('docx')
hiddenimports += collect_submodules('onnxruntime')
hiddenimports += collect_submodules('tokenizers')
hiddenimports += collect_submodules('certifi')
hiddenimports += ['imageio_ffmpeg']

# Bundle le binaire ffmpeg.exe d'imageio_ffmpeg pour les previews video
datas = [('assets/models', 'assets/models')]
try:
    import imageio_ffmpeg
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    if os.path.isfile(ffmpeg_exe):
        # On le copie dans imageio_ffmpeg/binaries/ pour que get_ffmpeg_exe()
        # le retrouve a l'execution du onedir
        datas.append((ffmpeg_exe, 'imageio_ffmpeg/binaries'))
except Exception:
    pass


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Organisateur',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Organisateur',
)

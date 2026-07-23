# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

datas = [('E:\\Project\\wallet\\wechat-auto\\config', 'config')]
hiddenimports = ['customtkinter', 'PIL', 'PIL._tkinter_finder', 'win32gui', 'win32api', 'win32con', 'win32process', 'pyautogui', 'pyperclip', 'yaml', 'openai', 'rapidocr_onnxruntime', 'imagehash', 'httpx', 'httpcore']
datas += collect_data_files('rapidocr_onnxruntime')
hiddenimports += collect_submodules('gui')
hiddenimports += collect_submodules('capture')
hiddenimports += collect_submodules('ocr')
hiddenimports += collect_submodules('detector')
hiddenimports += collect_submodules('llm')
hiddenimports += collect_submodules('automation')
hiddenimports += collect_submodules('taskqueue')
hiddenimports += collect_submodules('state')
hiddenimports += collect_submodules('recovery')


a = Analysis(
    ['E:\\Project\\wallet\\wechat-auto\\main_gui.py'],
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
    a.binaries,
    a.datas,
    [],
    name='WeChatAutoReply',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

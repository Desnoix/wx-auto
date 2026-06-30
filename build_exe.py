#!/usr/bin/env python
"""
打包 GUI 客户端为 exe。

用法:
    pip install pyinstaller
    python build_exe.py

输出: dist/WeChatAutoReply/WeChatAutoReply.exe
"""

import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Windows GBK 控制台兼容
_CHECK_MARK = "[OK]"


def build():
    try:
        import PyInstaller  # noqa
    except ImportError:
        print("请先安装 PyInstaller: pip install pyinstaller")
        sys.exit(1)

    # 隐藏导入 —— 防止 PyInstaller 漏掉动态导入的模块
    hidden = []
    for mod in [
        "customtkinter", "PIL", "PIL._tkinter_finder",
        "win32gui", "win32api", "win32con", "win32process",
        "pyautogui", "pyperclip",
        "yaml", "openai", "rapidocr_onnxruntime", "imagehash",
        "httpx", "httpcore",
    ]:
        hidden += ["--hidden-import", mod]

    # 数据文件：配置目录
    datas = [
        "--add-data", f"{os.path.join(PROJECT_ROOT, 'config')}{os.pathsep}config",
    ]

    # 收集所有 Python 包及其数据文件
    collect = []
    for pkg in ["gui", "capture", "ocr", "detector", "llm", "automation",
                 "taskqueue", "state", "recovery"]:
        collect += ["--collect-submodules", pkg]
    collect += ["--collect-data", "rapidocr_onnxruntime"]  # 包含内置 config.yaml

    cmd = (
        [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm"]
        + ["--name", "WeChatAutoReply"]
        + ["--windowed"]
        + ["--onefile"]               # 单文件 exe
        + hidden
        + datas
        + collect
        + [os.path.join(PROJECT_ROOT, "main_gui.py")]
    )

    print("=" * 60)
    print("打包中...")
    print("=" * 60)
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)

    if result.returncode == 0:
        exe_path = os.path.join(PROJECT_ROOT, "dist", "WeChatAutoReply.exe")
        size_mb = os.path.getsize(exe_path) / 1024 / 1024
        print(f"\n{_CHECK_MARK} 打包成功: {exe_path}")
        print(f"   大小: {size_mb:.1f} MB")
    else:
        print(f"\n{_CHECK_MARK} 打包失败")


if __name__ == "__main__":
    build()
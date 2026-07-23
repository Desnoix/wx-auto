#!/usr/bin/env python
"""
WeChat Auto-Reply 图形界面客户端入口。

用法:
    python main_gui.py
    或双击 dist/WeChatAutoReply.exe（打包后）

要求: customtkinter (pip install customtkinter)
打包: python build_exe.py
"""

import sys
import os


def _get_project_root() -> str:
    """获取项目根目录（兼容 PyInstaller 打包环境）。"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后，资源文件在 sys._MEIPASS 中
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


# 确保项目根目录在 sys.path 中
_project_root = _get_project_root()
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# 切换 CWD 到项目根目录，保证配置里的相对路径（screenshots/、logs/ 等）
# 与 GUI 面板使用的绝对路径一致，避免截图保存到 gui/screenshots/ 等错误位置。
os.chdir(_project_root)

# PyInstaller 多进程兼容：避免子进程重新导入 GUI
if getattr(sys, 'frozen', False):
    import multiprocessing
    multiprocessing.freeze_support()


def main():
    """启动 GUI 客户端。"""
    from gui.app import run_gui
    run_gui()


if __name__ == "__main__":
    main()
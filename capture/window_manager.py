"""
微信窗口管理器 — 通过 win32gui 查找、检查和管理微信窗口。
"""

import win32con
import win32gui
import win32process
import win32api


class WeChatWindowNotFoundError(Exception):
    """找不到微信窗口时抛出的异常。"""
    pass


class WeChatWindowManager:
    """管理微信窗口生命周期：查找、区域、可见性。"""

    WECHAT_CLASS = "Qt51514QWindowIcon"

    def __init__(self, class_name: str = None):
        self._class_name = class_name or self.WECHAT_CLASS
        self._hwnd = None

    def find_wechat_window(self) -> dict:
        """查找微信窗口，返回句柄和几何信息。"""
        hwnd = win32gui.FindWindow(self._class_name, None)
        if not hwnd:
            raise WeChatWindowNotFoundError(
                f"WeChat window not found (class={self._class_name})"
            )
        self._hwnd = hwnd
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        return {
            "hwnd": hwnd,
            "left": left,
            "top": top,
            "width": right - left,
            "height": bottom - top,
        }

    def get_window_rect(self, hwnd: int = None) -> tuple:
        """获取窗口矩形：(left, top, right, bottom)。"""
        h = hwnd or self._hwnd
        if not h:
            raise WeChatWindowNotFoundError("No window handle available")
        return win32gui.GetWindowRect(h)

    def is_minimized(self, hwnd: int = None) -> bool:
        """检查窗口是否最小化。"""
        h = hwnd or self._hwnd
        if not h:
            return True
        return win32gui.IsIconic(h)

    def is_window_visible(self, hwnd: int = None) -> bool:
        """检查窗口是否可见。"""
        h = hwnd or self._hwnd
        if not h:
            return False
        return win32gui.IsWindowVisible(h)

    def restore_window(self, hwnd: int = None) -> bool:
        """从最小化状态恢复窗口。"""
        h = hwnd or self._hwnd
        if not h:
            return False
        try:
            win32gui.ShowWindow(h, win32con.SW_RESTORE)
            return True
        except Exception:
            return False

    def bring_to_foreground(self, hwnd: int = None) -> bool:
        """将窗口置于前台（现代 Windows 上可能失败）。"""
        h = hwnd or self._hwnd
        if not h:
            return False
        try:
            win32gui.SetForegroundWindow(h)
            return True
        except Exception:
            return False

    def is_wechat_running(self, hwnd: int = None) -> bool:
        """检查微信窗口句柄是否仍然有效。"""
        h = hwnd or self._hwnd
        if not h:
            return False
        return win32gui.IsWindow(h)

    def refresh_hwnd(self) -> dict:
        """重新查找微信窗口（崩溃/恢复后使用）。"""
        return self.find_wechat_window()

    @property
    def hwnd(self) -> int:
        return self._hwnd
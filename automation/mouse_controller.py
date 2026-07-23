"""
微信自动化鼠标控制器

坐标系统说明：
  PrintWindow(PW_RENDERFULLCONTENT) 捕获完整窗口后裁掉标题栏，
  返回的图片仅含客户区。OCR 坐标即客户区相对坐标，
  通过 ClientToScreen 转换为屏幕坐标进行点击。
"""
import logging
import time
import pyautogui
import win32gui

logger = logging.getLogger(__name__)


class MouseController:
    def __init__(self, config: dict = None):
        self.config = config or {}
        pyautogui.PAUSE = 0.1
        pyautogui.FAILSAFE = True

    def _client_to_screen(self, x: int, y: int, hwnd: int) -> tuple:
        """将客户端区域坐标转换为屏幕坐标。

        考虑了 GetWindowRect（全窗口）与 PrintWindow 捕获的
        客户端区域之间的窗口边框/标题栏偏移。
        """
        # ClientToScreen converts client-area (x, y) to screen coordinates,
        # automatically accounting for the non-client border offset.
        screen_point = win32gui.ClientToScreen(hwnd, (x, y))
        return screen_point

    def click_at(self, x: int, y: int, hwnd: int = None, button: str = 'left') -> bool:
        try:
            if hwnd is not None:
                screen_x, screen_y = self._client_to_screen(x, y, hwnd)
                logger.info("[鼠标] click_at 客户端(%d, %d) → 屏幕(%d, %d) (hwnd=%d)",
                            x, y, screen_x, screen_y, hwnd)
                pyautogui.click(screen_x, screen_y, button=button)
            else:
                logger.info("[鼠标] click_at 无 hwnd，直接点击屏幕(%d, %d)", x, y)
                pyautogui.click(x, y, button=button)
            post_click_delay = self.config.get('post_click_delay', 1.5)
            time.sleep(post_click_delay)
            return True
        except Exception as e:
            logger.warning("[鼠标] click_at(%d, %d, hwnd=%s) 失败: %s", x, y, hwnd, e)
            return False

    def double_click_at(self, x: int, y: int, hwnd: int = None) -> bool:
        try:
            if hwnd is not None:
                screen_x, screen_y = self._client_to_screen(x, y, hwnd)
                pyautogui.doubleClick(screen_x, screen_y)
            else:
                pyautogui.doubleClick(x, y)

            post_click_delay = self.config.get('post_click_delay', 1.5)
            time.sleep(post_click_delay)
            return True
        except Exception as e:
            return False

    def click_center(self, bbox: list, hwnd: int = None) -> bool:
        center_x = int((bbox[0] + bbox[2]) / 2)
        center_y = int((bbox[1] + bbox[3]) / 2)
        logger.info("[鼠标] click_center bbox=%s → 中心(%d, %d) hwnd=%s",
                    bbox, center_x, center_y, hwnd)
        return self.click_at(center_x, center_y, hwnd)

    def click_region(self, region: dict, hwnd: int = None, button: str = 'left') -> bool:
        """点击比例区域的中心。

        使用客户端区域尺寸计算坐标，与 PrintWindow 捕获的
        OCR 坐标保持一致。

        Args:
            region: 包含 left、top、width、height 的字典（均为 0.0-1.0 浮点数）。
            hwnd: 用于坐标转换的窗口句柄。
            button: 鼠标按钮（'left' 或 'right'）。

        Returns:
            成功返回 True。
        """
        if hwnd:
            client_rect = win32gui.GetClientRect(hwnd)
            win_w = client_rect[2]  # 客户端区域宽度
            win_h = client_rect[3]  # 客户端区域高度
        else:
            win_w, win_h = pyautogui.size()

        cx = int(region.get("left", 0.0) * win_w + region.get("width", 0.0) * win_w / 2)
        cy = int(region.get("top", 0.0) * win_h + region.get("height", 0.0) * win_h / 2)

        return self.click_at(cx, cy, hwnd, button)

    def scroll_down(self, clicks: int = 3) -> None:
        pyautogui.scroll(-clicks)

    def scroll_up(self, clicks: int = 3) -> None:
        pyautogui.scroll(clicks)

    def get_screen_position(self, x: int, y: int, hwnd: int) -> tuple:
        return self._client_to_screen(x, y, hwnd)

"""
基于 PrintWindow 的微信后台截图模块。
无需前台窗口即可捕获窗口内容。
"""

import ctypes
import logging
import os
import time
from ctypes import wintypes
from datetime import datetime
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)

# --- Win32 API 声明 ---
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

PW_CLIENTONLY = 1

# RECT structure
class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]

# BITMAPINFOHEADER 结构体
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


class PrintWindowCapture:
    """通过 PrintWindow API 捕获微信窗口（无需前台）。"""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self._screenshot_dir = self.config.get("screenshot_dir", "screenshots")
        self._save_screenshots = self.config.get("save_screenshots", True)

    def capture_wechat(self, hwnd: int, max_retries: int = 3) -> Optional[Image.Image]:
        """通过 PrintWindow 捕获微信窗口内容。

        Args:
            hwnd: 要捕获的窗口句柄。
            max_retries: 黑屏或失败时的最大重试次数。

        Returns:
            窗口内容的 PIL Image，失败返回 None。
        """
        for attempt in range(max_retries):
            try:
                img = self._capture_single(hwnd)
                if img is None:
                    continue
                if self._is_black_screen(img):
                    logger.warning("[截图] 黑屏检测 (第 %d 次)，等待后重试", attempt + 1)
                    time.sleep(0.5)
                    continue
                return img
            except Exception:
                logger.warning("[截图] 捕获异常 (第 %d 次)", attempt + 1)
                time.sleep(0.5)
        logger.error("[截图] %d 次重试后仍然失败", max_retries)
        return None

    def _capture_single(self, hwnd: int) -> Optional[Image.Image]:
        """单次捕获，不重试。"""
        # 获取窗口矩形
        rect = RECT()
        result = user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if not result:
            logger.warning("GetWindowRect 失败")
            return None

        width = rect.right - rect.left
        height = rect.bottom - rect.top

        if width <= 0 or height <= 0:
            logger.warning(f"无效窗口尺寸: {width}x{height}")
            return None

        # 创建 DC
        hdc_window = user32.GetDC(hwnd)
        if not hdc_window:
            logger.warning("GetDC 失败")
            return None

        hdc_mem = None
        hbitmap = None
        img = None
        try:
            hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
            hbitmap = gdi32.CreateCompatibleBitmap(hdc_window, width, height)

            if not hbitmap:
                logger.warning("CreateCompatibleBitmap 失败")
                return None

            gdi32.SelectObject(hdc_mem, hbitmap)

            result = user32.PrintWindow(hwnd, hdc_mem, PW_CLIENTONLY)

            img = self._hbitmap_to_pil(hbitmap, hdc_mem, width, height)
            self._capture_post_process(img, hwnd)
            return img
        finally:
            if hbitmap:
                gdi32.DeleteObject(hbitmap)
            if hdc_mem:
                gdi32.DeleteDC(hdc_mem)
            if hdc_window:
                user32.ReleaseDC(hwnd, hdc_window)

    @staticmethod
    def _is_black_screen(img: Image.Image, threshold: int = 10, black_ratio: float = 0.95) -> bool:
        """检测图片是否基本全黑。

        Args:
            img: PIL Image。
            threshold: 像素亮度阈值（0-255），低于此值视为黑。
            black_ratio: 黑色像素占比超过此值时判定为黑屏。

        Returns:
            黑屏返回 True。
        """
        if img is None:
            return True
        # 采样检测（没必要遍历所有像素）
        # 取 100x100 均匀网格
        w, h = img.size
        step_x = max(1, w // 100)
        step_y = max(1, h // 100)
        dark = 0
        total = 0
        pixels = img.load()
        for x in range(0, w, step_x):
            for y in range(0, h, step_y):
                total += 1
                p = pixels[x, y]
                if isinstance(p, (tuple, list)):
                    brightness = (p[0] + p[1] + p[2]) / 3
                else:
                    brightness = p
                if brightness < threshold:
                    dark += 1
        return (dark / total) > black_ratio if total > 0 else True

    def _capture_post_process(self, img, hwnd):
        """截图后处理：按配置保存。"""
        if img is not None and self._save_screenshots:
            self._ensure_screenshot_dir()
            self.save_screenshot(img, "wechat")
        return img

    def capture_background(self, hwnd: int) -> Optional[Image.Image]:
        """capture_wechat 的别名。"""
        return self.capture_wechat(hwnd)

    def _hbitmap_to_pil(
        self, hbitmap: int, hdc: int, width: int, height: int
    ) -> Optional[Image.Image]:
        """使用 GetDIBits 将 Windows HBITMAP 转换为 PIL Image。"""
        try:
            bmp_info = BITMAPINFO()
            bmp_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmp_info.bmiHeader.biBitCount = 0

            # 调用 GetDIBits 获取位图信息（null bits = 查询）
            gdi32.GetDIBits(
                hdc, hbitmap, 0, 0, None,
                ctypes.byref(bmp_info), 0
            )

            # 设置为 32 位 BGRA 像素数据
            bmp_info.bmiHeader.biBitCount = 32
            bmp_info.bmiHeader.biCompression = 0  # BI_RGB

            if bmp_info.bmiHeader.biSizeImage == 0:
                bmp_info.bmiHeader.biSizeImage = width * height * 4

            # 分配缓冲区并获取实际位数据
            buf_size = bmp_info.bmiHeader.biSizeImage
            buf = ctypes.create_string_buffer(buf_size)

            gdi32.GetDIBits(
                hdc, hbitmap, 0, height, buf,
                ctypes.byref(bmp_info), 0
            )

            # 转换为 PIL Image (BGRA → RGBA)
            img = Image.frombuffer(
                "RGBA", (width, height), buf.raw, "raw", "BGRA", 0, 1
            )

            # 如果原点在左下角则翻转（正高度 = 自底向上）
            if bmp_info.bmiHeader.biHeight > 0:
                img = img.transpose(Image.FLIP_TOP_BOTTOM)

            return img.convert("RGB")

        except Exception as e:
            logger.error(f"HBITMAP 转 PIL 失败: {e}")
            return None

    def crop_region(self, image: Image.Image, region: dict) -> Image.Image:
        """按比例坐标裁剪图片。

        Args:
            image: PIL Image。
            region: 包含 left、top、width、height 的字典（均为 0.0-1.0 浮点数）。

        Returns:
            裁剪后的 PIL Image。
        """
        img_w, img_h = image.size
        x = int(region.get("left", 0.0) * img_w)
        y = int(region.get("top", 0.0) * img_h)
        w = int(region.get("width", 1.0) * img_w)
        h = int(region.get("height", 1.0) * img_h)
        return image.crop((x, y, x + w, y + h))

    def crop_left_panel(self, image: Image.Image) -> Image.Image:
        """使用默认比例裁剪左侧会话列表。"""
        return self.crop_region(image, {
            "left": 0.0, "top": 0.08, "width": 0.30, "height": 0.92
        })

    def save_screenshot(self, image: Image.Image, name: str = "capture") -> str:
        """将截图保存到磁盘，文件名带时间戳。

        Args:
            image: PIL Image。
            name: 文件名描述标签。

        Returns:
            文件路径，失败返回空字符串。
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"{timestamp}_{name}.png"
            filepath = os.path.join(self._screenshot_dir, filename)
            image.save(filepath, "PNG")
            return filepath
        except Exception as e:
            logger.error(f"保存截图失败: {e}")
            return ""

    def _ensure_screenshot_dir(self):
        """创建截图目录（如果不存在）。"""
        os.makedirs(self._screenshot_dir, exist_ok=True)
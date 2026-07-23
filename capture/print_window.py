"""
基于 PrintWindow 的微信后台截图模块。
无需前台窗口即可捕获窗口内容。
"""

import ctypes
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from datetime import datetime
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# --- Win32 API 声明 ---
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# 设置 DPI 感知：确保 GDI 坐标与物理像素一致（高 DPI 屏幕必需）
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

PW_RENDERFULLCONTENT = 2


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


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
        self._cache_ttl = self.config.get("capture_cache_ttl", 0.5)
        self._cached_image: Optional[Image.Image] = None
        self._cached_hwnd: Optional[int] = None
        self._cached_time: float = 0.0

        # 异步保存队列，避免 PNG 编码阻塞状态机循环
        self._save_queue_max = int(self.config.get("save_queue_max", 32))
        self._pending_lock = threading.Lock()
        self._pending_saves = 0
        self._save_executor: Optional[ThreadPoolExecutor] = None
        if self._save_screenshots:
            self._save_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="screenshot-save"
            )

    def capture_wechat(self, hwnd: int, max_retries: int = 3) -> Optional[Image.Image]:
        """通过 PrintWindow 捕获微信窗口内容。

        Args:
            hwnd: 要捕获的窗口句柄。
            max_retries: 黑屏或失败时的最大重试次数。

        Returns:
            窗口内容的 PIL Image，失败返回 None。
        """
        now = time.time()
        if (self._cached_image is not None
                and self._cached_hwnd == hwnd
                and (now - self._cached_time) < self._cache_ttl):
            return self._cached_image

        for attempt in range(max_retries):
            try:
                img = self._capture_single(hwnd)
                if img is None:
                    continue
                if self._is_black_screen(img):
                    logger.warning("[截图] 黑屏检测 (第 %d 次)，等待后重试", attempt + 1)
                    time.sleep(0.5)
                    continue
                self._cached_image = img
                self._cached_hwnd = hwnd
                self._cached_time = time.time()
                return img
            except Exception:
                logger.warning("[截图] 捕获异常 (第 %d 次)", attempt + 1)
                time.sleep(0.5)
        logger.error("[截图] %d 次重试后仍然失败", max_retries)
        return None

    def invalidate_cache(self) -> None:
        """手动使缓存失效，在需要强制重新截图时调用。"""
        self._cached_image = None

    def _capture_single(self, hwnd: int) -> Optional[Image.Image]:
        """单次捕获，不重试。"""
        window_rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(window_rect)):
            logger.warning("GetWindowRect 失败")
            return None

        width = window_rect.right - window_rect.left
        height = window_rect.bottom - window_rect.top

        if width <= 0 or height <= 0:
            logger.warning(f"无效窗口尺寸: {width}x{height}")
            return None

        hdc_window = user32.GetDC(hwnd)
        if not hdc_window:
            logger.warning("GetDC 失败")
            return None

        hdc_mem = None
        hbitmap = None
        try:
            hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
            hbitmap = gdi32.CreateCompatibleBitmap(hdc_window, width, height)

            if not hbitmap:
                logger.warning("CreateCompatibleBitmap 失败")
                return None

            gdi32.SelectObject(hdc_mem, hbitmap)

            pw_ok = user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)
            if not pw_ok:
                logger.debug("PrintWindow 返回 0，回退到 BitBlt")
                gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_window, 0, 0, 0x00CC0020)

            img = self._hbitmap_to_pil(hbitmap, hdc_mem, width, height)
            if img is None:
                return None

            img = self._strip_title_bar(img, hwnd, window_rect, height)
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
    def _strip_title_bar(img: Image.Image, hwnd: int, window_rect: RECT, bitmap_height: int) -> Image.Image:
        """裁掉标题栏，使返回的图片仅包含客户区，与下游坐标系一致。"""
        pt = POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        title_bar_h = pt.y - window_rect.top

        if 0 < title_bar_h < bitmap_height:
            img = img.crop((0, title_bar_h, img.width, img.height))

        return img

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
        arr = np.asarray(img)
        if arr.ndim == 3:
            brightness = arr.mean(axis=2)
        else:
            brightness = arr.astype(np.float32)
        dark_ratio = (brightness < threshold).sum() / brightness.size
        return dark_ratio > black_ratio

    def _capture_post_process(self, img, hwnd):
        """截图后处理：按配置异步保存到磁盘（不阻塞状态机循环）。"""
        if img is None or not self._save_screenshots:
            return img
        if self._save_executor is None:
            return img

        with self._pending_lock:
            if self._pending_saves >= self._save_queue_max:
                logger.warning(
                    "[截图] 保存队列已满 (%d)，丢弃本次截图以避免内存堆积",
                    self._pending_saves,
                )
                return img
            self._pending_saves += 1

        try:
            self._save_executor.submit(self._save_worker, img, "wechat")
        except RuntimeError:
            # executor 已关闭（关机路径），回退到同步保存
            with self._pending_lock:
                self._pending_saves -= 1
            self._save_sync(img, "wechat")
        return img

    def _save_worker(self, image: Image.Image, name: str) -> None:
        """在后台线程执行的实际保存动作。"""
        try:
            self._save_sync(image, name)
        finally:
            with self._pending_lock:
                self._pending_saves -= 1

    def _save_sync(self, image: Image.Image, name: str) -> str:
        """同步保存图片到磁盘。"""
        try:
            self._ensure_screenshot_dir()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"{timestamp}_{name}.png"
            filepath = os.path.join(self._screenshot_dir, filename)
            image.save(filepath, "PNG")
            return filepath
        except Exception as e:
            logger.error("保存截图失败: %s", e)
            return ""

    def close(self, wait: bool = True) -> None:
        """关闭后台保存线程，等待未完成的保存任务落盘。"""
        if self._save_executor is not None:
            self._save_executor.shutdown(wait=wait)
            self._save_executor = None

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
        """将截图同步保存到磁盘（供外部调用；内部走异步路径）。

        Args:
            image: PIL Image。
            name: 文件名描述标签。

        Returns:
            文件路径，失败返回空字符串。
        """
        return self._save_sync(image, name)

    def _ensure_screenshot_dir(self):
        """创建截图目录（如果不存在）。"""
        os.makedirs(self._screenshot_dir, exist_ok=True)
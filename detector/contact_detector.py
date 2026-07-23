"""微信自动回复系统 - 联系人检测和定位模块。"""
import re
from typing import List, Dict, Optional
from PIL import Image
from ocr.rapid_ocr import OCREngine, OCRResult


class ContactDetector:
    """检测并定位微信左侧面板中的联系人。"""

    def __init__(self, ocr_engine: OCREngine, crop_region: dict = None):
        """初始化联系人检测器。

        Args:
            ocr_engine: 用于文本识别的 OCR 引擎
            crop_region: 左侧面板裁剪区域 {left, top, width, height}，比例值 0.0-1.0
        """
        self.ocr_engine = ocr_engine
        self._crop = crop_region or {"left": 0.0, "top": 0.08, "width": 0.30, "height": 0.92}

    def get_contact_positions(self, image: Image.Image) -> List[Dict]:
        """获取左侧面板中所有联系人的位置。

        Args:
            image: 微信窗口的 PIL Image

        Returns:
            联系人字典列表，包含 name、bbox、center 和 y_order
            bbox 坐标为原始图片（窗口相对）坐标系。
        """
        if not isinstance(image, Image.Image):
            return []

        img_width, img_height = image.size
        crop_x = int(self._crop.get("left", 0.0) * img_width)
        crop_y = int(self._crop.get("top", 0.08) * img_height)
        crop_w = int(self._crop.get("width", 0.30) * img_width)
        crop_h = int(self._crop.get("height", 0.92) * img_height)
        left_panel = image.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))

        ocr_results = self.ocr_engine.ocr_image(left_panel)

        # Offset bbox coordinates from crop-relative to original-image-relative
        for r in ocr_results:
            r.bbox[0] += crop_x
            r.bbox[1] += crop_y
            r.bbox[2] += crop_x
            r.bbox[3] += crop_y

        if not ocr_results:
            return []

        contacts = []
        processed_texts = set()

        for result in ocr_results:
            text = result.text.strip()
            if not text or text in processed_texts:
                continue

            processed_texts.add(text)

            bbox = result.bbox
            center = self.compute_center(bbox)
            y_order = center[1]

            contacts.append({
                'name': text,
                'bbox': bbox,
                'center': center,
                'y_order': y_order
            })

        contacts.sort(key=lambda c: c['y_order'])

        return contacts

    def find_contact_by_name(self, image: Image.Image, target_name: str) -> Optional[Dict]:
        """按名称查找特定联系人。

        Args:
            image: 微信窗口的 PIL Image
            target_name: 要查找的联系人名称

        Returns:
            联系人字典或 None（未找到）
        """
        if not isinstance(image, Image.Image) or not target_name:
            return None

        contacts = self.get_contact_positions(image)
        target_clean = self._strip_punctuation(target_name.lower())

        for contact in contacts:
            contact_clean = self._strip_punctuation(contact['name'].lower())
            if target_clean in contact_clean or contact_clean in target_clean:
                return contact

        return None

    @staticmethod
    def _strip_punctuation(text: str) -> str:
        """去除中英文标点符号，仅保留文字、字母、数字。
        
        解决 RapidOCR 可能吞掉标点导致名称匹配失败的问题。
        """
        # 保留中文、英文、数字、空格
        return re.sub(r'[^\w\s\u4e00-\u9fff]', '', text)

    def find_contact_by_name_with_retry(self, image: Image.Image, target_name: str, max_retries: int = 3) -> Optional[Dict]:
        """Find a contact by name with retry logic.

        Args:
            image: PIL Image of WeChat window
            target_name: Name of contact to find
            max_retries: Maximum number of retry attempts

        Returns:
            Contact dictionary or None if not found after retries
        """
        for attempt in range(max_retries):
            contact = self.find_contact_by_name(image, target_name)
            if contact:
                return contact

        return None

    @staticmethod
    def compute_center(bbox: list) -> tuple:
        """从边界框计算中心点。

        Args:
            bbox: 边界框 [x1, y1, x2, y2] 或更长的列表

        Returns:
            中心坐标 (x, y)
        """
        if not bbox or len(bbox) < 4:
            return (0, 0)

        center_x = (bbox[0] + bbox[2]) // 2
        center_y = (bbox[1] + bbox[3]) // 2

        return (center_x, center_y)

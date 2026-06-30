"""微信自动回复系统 - 消息提取模块。"""
from typing import List, Dict, Optional
from PIL import Image
from ocr.rapid_ocr import OCREngine, OCRResult


class MessageDetector:
    """使用 OCR 从微信消息区域提取消息。"""

    def __init__(self, ocr_engine: OCREngine):
        """初始化消息检测器。

        Args:
            ocr_engine: OCR 引擎实例
        """
        self.ocr_engine = ocr_engine

    def extract_messages(self, image: Image.Image, max_messages: int = 20) -> List[Dict]:
        """从消息区域提取所有消息。

        Args:
            image: 微信窗口的 PIL Image

        Returns:
            消息字典列表，包含 role、content 和 bbox
            bbox 坐标为原始图片（窗口相对）坐标系。
        """
        if not isinstance(image, Image.Image):
            return []

        img_width, img_height = image.size
        crop_x = int(0.30 * img_width)
        crop_y = int(0.10 * img_height)
        crop_w = int(1.00 * img_width) - crop_x
        crop_h = int(0.85 * img_height) - crop_y
        message_area = image.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))

        ocr_results = self.ocr_engine.ocr_image(message_area)

        # Offset bbox coordinates from crop-relative to original-image-relative
        for r in ocr_results:
            r.bbox[0] += crop_x
            r.bbox[1] += crop_y
            r.bbox[2] += crop_x
            r.bbox[3] += crop_y

        if not ocr_results:
            return []

        messages = self._convert_to_messages(ocr_results, max_messages, img_width)

        return messages

    def extract_last_message(self, image: Image.Image) -> Optional[Dict]:
        """Extract only the most recent (last) message.

        Args:
            image: PIL Image of WeChat window

        Returns:
            Last message dictionary or None if no messages found
        """
        messages = self.extract_messages(image, max_messages=10)

        if not messages:
            return None

        return messages[-1]

    @staticmethod
    def _sort_by_position(results: List[OCRResult]) -> List[OCRResult]:
        """Sort OCR results top-to-bottom, then left-to-right.

        Args:
            results: List of OCR results to sort

        Returns:
            Sorted list of OCR results
        """
        sorted_results = sorted(results, key=lambda r: (r.bbox[1], r.bbox[0]))
        return sorted_results

    def _convert_to_messages(self, ocr_results: List[OCRResult], max_messages: int, img_width: int = None) -> List[Dict]:
        """Convert OCR results to message dictionaries with role detection.

        WeChat renders contact messages left-aligned and user's own messages
        right-aligned.  We use the bbox center X position relative to the
        message-area midpoint to infer the sender role.

        Args:
            ocr_results: List of OCR results
            max_messages: Maximum number of messages to return
            img_width: Full image width (for role threshold detection)

        Returns:
            List of message dictionaries with role, content, and bbox
        """
        sorted_results = self._sort_by_position(ocr_results)

        # Role detection threshold: messages with center_x < 65% of window
        # width are treated as incoming (contact), else outgoing (self).
        threshold_x = int(0.65 * img_width) if img_width else 0

        messages = []
        count = 0

        for result in sorted_results:
            if count >= max_messages:
                break

            text = result.text.strip()
            if not text:
                continue

            bbox = result.bbox
            center_x = (bbox[0] + bbox[2]) / 2
            role = "assistant" if center_x >= threshold_x else "user"

            messages.append({
                'role': role,
                'content': text,
                'bbox': bbox
            })

            count += 1

        return messages

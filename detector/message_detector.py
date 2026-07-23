"""微信自动回复系统 - 消息提取模块。"""
import re
from typing import List, Dict, Optional
from PIL import Image
from ocr.rapid_ocr import OCREngine, OCRResult


# 微信消息间的时间/日期分隔标签，需从 OCR 结果中滤除
_TIME_RE = re.compile(
    r'^\s*'
    r'(?:\d{4}\s*年\s*)?(?:\d{1,2}\s*月\s*\d{1,2}\s*日\s*)?'   # 可选日期：2024年1月1日 / 1月1日
    r'(?:昨天|前天|今天|星期[一二三四五六日天]|周[一二三四五六日天])?\s*'  # 可选相对日 / 星期
    r'(?:上午|下午|凌晨|早上|中午|晚上)?\s*'                  # 可选时段
    r'\d{1,2}[:：]\d{2}'                                       # 必需 HH:MM
    r'\s*$',
    re.UNICODE,
)

# 裁剪边界截断产生的时间戳残片，如 "天16:21"（"昨天HH:MM" 被切掉 "昨"）
# 结构：≤3 个非数字字符（可能是被切残的"昨/前/今/上午/下午"）+ HH:MM
_TIME_FRAGMENT_RE = re.compile(
    r'^\s*[^\d\s]{1,3}\s*\d{1,2}[:：]\d{2}\s*$',
    re.UNICODE,
)

# 无任何字母/汉字/常用符号的纯数字标点串，视为 OCR 噪声（如残留时间碎片）
_NOISE_RE = re.compile(r'^[\d\s\.\-\:：/]+$')

# 短文本末尾的孤立西文标点（真实中文消息通常用"。"或无标点，"后再."之类多为 OCR 断裂）
_FRAGMENT_RE = re.compile(r'^.{1,3}[\.,;:\'"`\-_]$')


def _is_timestamp_label(text: str) -> bool:
    """判断是否为微信 UI 的时间/日期分隔标签，而非真实消息内容。"""
    if not text:
        return True
    if _TIME_RE.match(text):
        return True
    if _TIME_FRAGMENT_RE.match(text):
        return True
    if _NOISE_RE.match(text) and len(text.strip()) <= 8:
        return True
    return False


def _looks_like_ocr_fragment(text: str) -> bool:
    """判断是否为 OCR 断裂产生的短碎片（≤3 字且以孤立西文标点结尾）。"""
    return bool(_FRAGMENT_RE.match(text))


class MessageDetector:
    """使用 OCR 从微信消息区域提取消息。"""

    def __init__(
        self,
        ocr_engine: OCREngine,
        crop_region: dict = None,
        min_confidence: float = 0.7,
    ):
        """初始化消息检测器。

        Args:
            ocr_engine: OCR 引擎实例
            crop_region: 消息区域裁剪配置 {left, top, width, height}，比例值 0.0-1.0
            min_confidence: 消息内容的最低置信度（比通用 OCR 阈值更严格，过滤不确定结果）
        """
        self.ocr_engine = ocr_engine
        self._crop = crop_region or {"left": 0.30, "top": 0.10, "width": 0.70, "height": 0.75}
        self._min_confidence = min_confidence

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
        crop_x = int(self._crop.get("left", 0.30) * img_width)
        crop_y = int(self._crop.get("top", 0.10) * img_height)
        crop_w = int(self._crop.get("width", 0.70) * img_width)
        crop_h = int(self._crop.get("height", 0.75) * img_height)
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
            if _is_timestamp_label(text):
                continue
            if result.confidence < self._min_confidence:
                continue
            if _looks_like_ocr_fragment(text):
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

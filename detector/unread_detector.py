"""微信自动回复系统 - 未读联系人检测模块。"""
from typing import List, Dict, Optional
from PIL import Image
from ocr.rapid_ocr import OCREngine, OCRResult


class UnreadDetector:
    """检测微信左侧面板中联系人的未读消息数。"""

    def __init__(self, ocr_engine: OCREngine, config: dict = None):
        """初始化未读检测器。

        Args:
            ocr_engine: 用于文本识别的 OCR 引擎
            config: 可选配置字典
        """
        self.ocr_engine = ocr_engine
        self.config = config or {}

    def find_unread_contacts(self, image: Image.Image) -> List[Dict]:
        """查找有未读消息标记的联系人。

        Args:
            image: 微信窗口的 PIL Image

        Returns:
            未读联系人列表，包含 name、bbox、unread_count 和 unread_bbox。
            bbox 坐标为原始图片（窗口相对）坐标系。
        """
        if not isinstance(image, Image.Image):
            return []

        img_width, img_height = image.size
        crop_x = int(0.0 * img_width)
        crop_y = int(0.08 * img_height)
        crop_w = int(0.30 * img_width) - crop_x
        crop_h = int(0.92 * img_height) - crop_y
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

        contacts = self._match_name_to_badge(ocr_results)
        return self._deduplicate_contacts(contacts)

    def _is_unread_badge(self, text: str) -> bool:
        """检查文本是否像未读数角标。

        Args:
            text: 待检查的 OCR 文本

        Returns:
            看起来是未读数返回 True
        """
        text = text.strip()

        if not text:
            return False

        if text.isdigit():
            count = int(text)
            return 1 <= count <= 99

        if text.endswith('+'):
            num_part = text[:-1]
            if num_part.isdigit():
                count = int(num_part)
                return 1 <= count <= 99

        return False

    def _match_name_to_badge(self, ocr_results: List[OCRResult]) -> List[Dict]:
        """匹配联系人名称到附近的未读角标。

        Args:
            ocr_results: 左侧面板的 OCR 结果列表

        Returns:
            匹配到的未读联系人列表
        """
        contacts = []
        processed_texts = set()

        for result in ocr_results:
            text = result.text.strip()
            if not text or text in processed_texts:
                continue

            processed_texts.add(text)

            if self._is_unread_badge(text):
                continue

            unread_contacts = self._find_unread_for_name(result, ocr_results)
            for contact in unread_contacts:
                contacts.append(contact)
                processed_texts.add(contact['name'])

        return contacts

    def _find_unread_for_name(self, name_result: OCRResult, all_results: List[OCRResult]) -> List[Dict]:
        """为给定的联系人名称查找未读角标。

        Args:
            name_result: 包含联系人名称的 OCR 结果
            all_results: 区域内的所有 OCR 结果

        Returns:
            未读联系人字典列表
        """
        contacts = []
        name = name_result.text.strip()

        if not name:
            return contacts

        name_bbox = name_result.bbox

        unread_results = []
        for result in all_results:
            text = result.text.strip()
            if self._is_unread_badge(text):
                unread_results.append((text, result.bbox))

        if not unread_results:
            return contacts

        unread_results.sort(key=lambda x: self._distance_to_name(name_bbox, x[1]))

        best_match = unread_results[0]
        unread_count_text = best_match[0]
        unread_bbox = best_match[1]

        unread_count = self._parse_unread_count(unread_count_text)

        contacts.append({
            'name': name,
            'name_bbox': name_bbox,
            'contact_center': ((name_bbox[0] + name_bbox[2]) // 2,
                               (name_bbox[1] + name_bbox[3]) // 2),
            'unread_count': unread_count,
            'unread_bbox': unread_bbox
        })

        return contacts

    def _distance_to_name(self, name_bbox: list, unread_bbox: list) -> float:
        """Calculate distance between name and unread badge bbox centers.

        Unread badges must be to the RIGHT of the contact name (badge x1 > name x2).
        If badge is to the LEFT, penalize heavily to prevent cross-contact matching.

        Args:
            name_bbox: Bounding box [x1, y1, x2, y2] (window-relative)
            unread_bbox: Bounding box [x1, y1, x2, y2] (window-relative)

        Returns:
            Weighted distance score (lower = better match)
        """
        name_cx = (name_bbox[0] + name_bbox[2]) / 2
        name_cy = (name_bbox[1] + name_bbox[3]) / 2
        unread_cx = (unread_bbox[0] + unread_bbox[2]) / 2
        unread_cy = (unread_bbox[1] + unread_bbox[3]) / 2

        # Euclidean distance
        distance = ((name_cx - unread_cx) ** 2 + (name_cy - unread_cy) ** 2) ** 0.5

        # Penalty: badge must be to the RIGHT of the name
        if unread_bbox[0] <= name_bbox[2]:
            distance += 1000  # Badge is left of or overlapping name — wrong contact

        # Boost vertical alignment: prefer badges at similar Y to name
        vertical_offset = abs(name_cy - unread_cy)
        distance += vertical_offset * 0.5

        return distance

    def _parse_unread_count(self, text: str) -> int:
        """Parse unread count from text.

        Args:
            text: Unread badge text

        Returns:
            Parsed unread count
        """
        text = text.strip()

        if text.isdigit():
            return int(text)

        if text.endswith('+'):
            num_part = text[:-1]
            if num_part.isdigit():
                return int(num_part)

        return 0

    def _deduplicate_contacts(self, contacts: List[Dict]):
        """Deduplicate contacts by name, keeping highest unread count.

        Args:
            contacts: List of contact dictionaries to deduplicate
        """
        name_map = {}

        for contact in contacts:
            name = contact['name']
            if name in name_map:
                existing = name_map[name]
                if contact['unread_count'] > existing['unread_count']:
                    name_map[name] = contact
            else:
                name_map[name] = contact

        return list(name_map.values())

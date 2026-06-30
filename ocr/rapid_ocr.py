"""基于 rapidocr_onnxruntime 的 OCR 引擎。"""

from dataclasses import dataclass
from typing import Optional

import PIL.Image


@dataclass
class OCRResult:
    """OCR 操作结果。"""

    text: str
    confidence: float
    bbox: list


class OCREngine:
    """OCR 引擎，支持懒加载和重试逻辑。"""

    def __init__(self, config: Optional[dict] = None):
        """初始化 OCR 引擎。

        Args:
            config: 可选配置字典，支持：
                - confidence_threshold: 最小置信度（默认 0.5）
                - max_retries: 最大重试次数（默认 3）
                - retry_delay: 重试间隔（秒，默认 1）
        """
        self.config = config or {}
        self.confidence_threshold = self.config.get(
            "confidence_threshold", 0.5
        )
        self.max_retries = self.config.get("max_retries", 3)
        self.retry_delay = self.config.get("retry_delay", 1.0)
        self._engine = None

    def _ensure_engine(self) -> None:
        """确保 OCR 引擎已初始化（懒加载）。"""
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR
            self._engine = RapidOCR()

    def ocr_image(
        self, image: PIL.Image
    ) -> list[OCRResult]:
        """对整张图片进行 OCR。

        Args:
            image: 待处理的 PIL Image

        Returns:
            OCRResult 列表，包含 text、confidence 和 bbox。
            bbox 格式为 [x1, y1, x2, y2]（左上角、右下角）。
            未检测到文本或失败时返回空列表。
        """
        self._ensure_engine()
        import numpy as np

        if self._engine is None:
            return []

        try:
            img_array = np.array(image)
            result = self._engine(img_array)

            if result is None:
                return []

            # RapidOCR 输出格式（本机验证）：
            # result = (boxes_data, texts_data)
            # boxes_data 中每个元素为：
            #   [ [[x1,y1],[x2,y2],[x3,y3],[x4,y4]], text_str, confidence_float ]
            if len(result) < 1 or not result[0]:
                return []

            raw_boxes = result[0]

            ocr_results = []
            for entry in raw_boxes:
                if len(entry) < 3:
                    continue
                points = entry[0]   # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                text = str(entry[1]) if entry[1] else ""
                confidence = float(entry[2]) if entry[2] else 0.0

                if confidence < self.confidence_threshold:
                    continue
                if not text.strip():
                    continue

                # 将四边形归一化为 [x1, y1, x2, y2] 矩形边界框
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                bbox = [min(xs), min(ys), max(xs), max(ys)]

                ocr_results.append(
                    OCRResult(text=text, confidence=confidence, bbox=bbox)
                )

            return ocr_results

        except Exception:
            return []

    def ocr_region(
        self, image: PIL.Image, region: dict
    ) -> list[OCRResult]:
        """对图片的指定区域进行 OCR。

        Args:
            image: PIL Image
            region: 区域字典，键为：
                - left: 左边界 (0.0-1.0)
                - top: 上边界 (0.0-1.0)
                - width: 区域宽度 (0.0-1.0)
                - height: 区域高度 (0.0-1.0)

        Returns:
            OCRResult 列表。
        """
        cropped = self._crop_proportional(image, region)
        return self.ocr_image(cropped)

    def ocr_text(self, image: PIL.Image) -> str:
        """对整张图片 OCR 并返回拼接后的文本。

        Args:
            image: PIL Image

        Returns:
            所有检测文本以空格拼接。
        """
        results = self.ocr_image(image)
        return " ".join(result.text for result in results)

    def ocr_region_text(
        self, image: PIL.Image, region: dict
    ) -> str:
        """对区域 OCR 并返回拼接后的文本。

        Args:
            image: PIL Image
            region: 区域字典

        Returns:
            拼接后的文本。
        """
        results = self.ocr_region(image, region)
        return " ".join(result.text for result in results)

    def ocr_with_retry(
        self, image: PIL.Image, max_retries: Optional[int] = None
    ) -> list[OCRResult]:
        """带重试逻辑的 OCR。

        Args:
            image: PIL Image
            max_retries: 覆盖默认最大重试次数

        Returns:
            最后一次成功的结果列表，全部失败返回空列表。
        """
        retries = max_retries or self.max_retries

        for attempt in range(retries):
            try:
                return self.ocr_image(image)
            except Exception:
                if attempt < retries - 1:
                    import time

                    time.sleep(self.retry_delay)
                continue

        return []

    def _crop_proportional(
        self, image: PIL.Image, region: dict
    ) -> PIL.Image:
        """按比例裁剪图片（坐标系 0.0-1.0）。

        Args:
            image: PIL Image
            region: 区域字典，键为 left、top、width、height（0.0-1.0）

        Returns:
            裁剪后的 PIL Image。
        """
        img_width, img_height = image.size

        left = int(region.get("left", 0.0) * img_width)
        top = int(region.get("top", 0.0) * img_height)
        width = int(region.get("width", 1.0) * img_width)
        height = int(region.get("height", 1.0) * img_height)

        right = left + width
        bottom = top + height

        return image.crop((left, top, right, bottom))

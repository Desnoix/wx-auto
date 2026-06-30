"""VL 视觉检测器 — 使用多模态模型直接分析微信截图。

替代方案：
  - monitor/hash_monitor.py（哈希变化检测，精度不够）
  - detector/unread_detector.py（OCR 未读角标检测，容易漏）
"""

import base64
import io
import json
import logging
import re
from typing import List, Dict, Optional
from PIL import Image

logger = logging.getLogger(__name__)


class VLDetector:
    """使用 VL 多模态模型分析微信截图。

    把整张截图发给 VL 模型，直接识别：
    - 左侧会话列表有哪些联系人
    - 哪些联系人有未读消息
    - 每个联系人的大致位置（用于点击）
    """

    def __init__(self, llm_provider):
        """初始化 VL 检测器。

        Args:
            llm_provider: 支持 analyze_image 方法的 LLM 提供者。
        """
        self._llm = llm_provider

    def find_unread_contacts(self, image: Image.Image) -> List[Dict]:
        """分析截图，找出有未读消息的联系人。

        Args:
            image: 微信窗口的全屏截图（PIL Image）。

        Returns:
            未读联系人列表，每个元素：
            {
                "name": "联系人名称",
                "unread_count": 3,        # 未读数，未知为 1
                "name_bbox": [x1,y1,x2,y2], # 名称在图片中的大致位置
            }
            无未读时返回空列表。
        """
        prompt = """你是一个微信截图分析助手。分析这张微信 PC 版截图，找出左侧会话列表中
所有有未读消息的联系人。

未读消息的特征：
1. 联系人名称右侧有红色圆形角标，里面写着数字（如 3、99+）
2. 如果无数字但有红点，视为 1 条未读
3. 当前对话窗口有未回复的内容，视为未读

请严格按照以下 JSON 格式返回，不要加 markdown 标记，不要加多余文字：

{
  "contacts": [
    {
      "name": "联系人名称",
      "unread_count": 3,
      "bbox": [x1, y1, x2, y2]
    }
  ]
}

bbox 是联系人名称在截图中的大致位置 [左上角x, 左上角y, 右下角x, 右下角y]，
不需要特别精确，能用来估算点击位置即可。
如果没有任何未读消息，返回 {"contacts": []}。"""

        response = self._llm.analyze_image(image, prompt)
        if not response:
            logger.warning("[VL检测] LLM 返回为空")
            return []

        return self._parse_response(response)

    def _parse_response(self, response: str) -> List[Dict]:
        """从 LLM 回复中解析 JSON。"""
        # 尝试直接解析
        try:
            data = json.loads(response)
            contacts = data.get("contacts", [])
            if contacts:
                logger.info("[VL检测] 解析到 %d 个未读联系人: %s",
                            len(contacts), [c.get("name", "?") for c in contacts])
            return contacts
        except json.JSONDecodeError:
            pass

        # 尝试从 markdown 代码块中提取
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', response)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                contacts = data.get("contacts", [])
                if contacts:
                    logger.info("[VL检测] 从代码块解析到 %d 个未读联系人", len(contacts))
                return contacts
            except json.JSONDecodeError:
                pass

        # 尝试找花括号
        brace_match = re.search(r'\{[\s\S]*\}', response)
        if brace_match:
            try:
                data = json.loads(brace_match.group(0))
                contacts = data.get("contacts", [])
                return contacts
            except json.JSONDecodeError:
                pass

        logger.warning("[VL检测] 无法解析 LLM 回复: %.200s", response)
        return []

    def detect_general(self, image: Image.Image, question: str) -> str:
        """通用 VL 问答。

        Args:
            image: 截图。
            question: 问题文本。

        Returns:
            LLM 回答文本。
        """
        return self._llm.analyze_image(image, question) or ""
import base64
import logging
from io import BytesIO
from time import sleep
from typing import Any, Optional

from PIL import Image
from openai import OpenAI, APIError, RateLimitError, APITimeoutError, AuthenticationError

from llm.provider import LLMProvider

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """OpenAI 兼容的 LLM 提供者。"""

    def __init__(self, config: dict):
        """初始化 OpenAI 提供者。"""
        super().__init__(config)

        self._base_url = config.get("base_url")
        self._api_key = config.get("api_key")
        self._model = config.get("model")
        self._temperature = config.get("temperature", 0.7)
        self._max_tokens = config.get("max_tokens", 1000)
        self._timeout = config.get("timeout", 30)
        self._max_retries = config.get("max_retries", 3)

        self._client = OpenAI(base_url=self._base_url, api_key=self._api_key, timeout=self._timeout, max_retries=0)

    def generate_reply(self, messages: list[dict], system_prompt: str) -> str:
        """使用 OpenAI 兼容接口生成回复。"""
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        return self._retry_call(self._client.chat.completions.create, model=self._model, messages=full_messages, temperature=self._temperature, max_tokens=self._max_tokens)

    def analyze_image(self, image: Image.Image, prompt: str) -> str:
        """使用视觉模型分析图片。

        Args:
            image: 待分析的 PIL Image。
            prompt: 分析指令文本。

        Returns:
            模型回复文本，失败返回空字符串。
        """
        # 缩放图片到合理尺寸（最长边不超过 1024px）
        resized = self._resize_for_vision(image, max_size=1024)

        # 编码为 base64 JPEG
        buffered = BytesIO()
        resized.save(buffered, format="JPEG", quality=85)
        img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{img_base64}"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url, "detail": "low"},
                    },
                ],
            }
        ]

        return self._retry_call(
            self._client.chat.completions.create,
            model=self._model,
            messages=messages,
            max_tokens=self._max_tokens,
            temperature=0.1,
        )

    @staticmethod
    def _resize_for_vision(image: Image.Image, max_size: int = 1024) -> Image.Image:
        """保持宽高比缩放图片，最长边不超过 max_size。"""
        w, h = image.size
        if max(w, h) <= max_size:
            return image
        ratio = max_size / max(w, h)
        return image.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    def _retry_call(self, func: Any, *args: Any, **kwargs: Any) -> str:
        """带重试逻辑的函数执行，处理临时错误。"""
        last_error = None

        for attempt in range(self._max_retries):
            try:
                response = func(*args, **kwargs)
                message = response.choices[0].message
                reasoning = getattr(message, "reasoning_content", None)
                if reasoning:
                    logger.debug("模型思考: %s", reasoning)
                content = message.content
                if content is None:
                    finish_reason = response.choices[0].finish_reason
                    logger.warning("模型返回空内容 (finish_reason=%s)", finish_reason)
                    if finish_reason == "length":
                        return ""
                    last_error = Exception(f"模型返回空内容 (finish_reason={finish_reason})")
                    if attempt < self._max_retries - 1:
                        sleep(2 ** attempt)
                    continue
                return content.strip()
            except APITimeoutError:
                last_error = Exception("API 超时")
                if attempt < self._max_retries - 1:
                    sleep(2 ** attempt)
            except RateLimitError:
                last_error = Exception("请求频率超限")
                if attempt < self._max_retries - 1:
                    sleep(5)
            except AuthenticationError as e:
                logger.error("认证错误: %s", e)
                return ""
            except APIError as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    sleep(2 ** attempt)
            except Exception as e:
                last_error = e
                logger.error("意外错误: %s", e)
                return ""

        logger.error("重试 %d 次后仍然失败: %s", self._max_retries, last_error)
        return ""

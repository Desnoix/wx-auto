from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """LLM 提供者抽象基类。"""

    def __init__(self, config: dict):
        """用配置初始化提供者。"""
        self._config = config

    @abstractmethod
    def generate_reply(self, messages: list[dict], system_prompt: str) -> str:
        """从 LLM 生成回复。

        Args:
            messages: 消息字典列表，包含 'role' 和 'content' 键。
            system_prompt: 系统提示词，前置到对话中。

        Returns:
            生成的回复文本。
        """
        raise NotImplementedError

    def analyze_image(self, image: "PIL.Image.Image", prompt: str) -> str:
        """分析图片内容并返回文本回复。

        基类默认实现抛出 NotImplementedError，子类（视觉模型）应覆盖此方法。

        Args:
            image: 待分析的 PIL Image。
            prompt: 分析指令文本。

        Returns:
            模型回复文本，不支持视觉时返回空字符串。
        """
        raise NotImplementedError("当前 LLM 提供者不支持图片分析")

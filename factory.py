"""组件工厂 — 统一的组件组装逻辑，供 main.py 和 GUI 引擎共享。"""

import logging

from capture.window_manager import WeChatWindowManager
from capture.print_window import PrintWindowCapture
from ocr.rapid_ocr import OCREngine
from llm.openai_provider import OpenAIProvider
from detector.vl_detector import VLDetector
from detector.contact_detector import ContactDetector
from detector.message_detector import MessageDetector
from automation.mouse_controller import MouseController
from automation.keyboard_controller import KeyboardController
from taskqueue.task_queue import TaskQueue
from state.state_machine import StateMachine
from recovery.watchdog import Watchdog

logger = logging.getLogger(__name__)


def build_components(config: dict) -> dict:
    """根据配置字典组装所有组件。

    Args:
        config: 完整配置字典（从 config.yaml 加载）。

    Returns:
        包含所有组件的字典，可直接传入 StateMachine。
    """
    window_manager = WeChatWindowManager(
        class_name=config.get("wechat", {}).get("class_name")
    )
    print_window = PrintWindowCapture(config.get("capture", {}))

    ocr_engine = OCREngine(config.get("ocr", {}))

    llm_config = config.get("llm", {})
    llm_provider = OpenAIProvider(llm_config) if llm_config.get("api_key") else None

    if llm_provider is None:
        logger.warning("LLM API 密钥未配置 — 回复生成已禁用")

    vl_detector = VLDetector(llm_provider) if llm_provider else None

    crop_regions = config.get("capture", {}).get("crop_regions", {})
    contact_detector = ContactDetector(
        ocr_engine, crop_region=crop_regions.get("left_panel")
    )
    ocr_cfg = config.get("ocr", {})
    message_detector = MessageDetector(
        ocr_engine,
        crop_region=crop_regions.get("message_area"),
        min_confidence=float(ocr_cfg.get("message_min_confidence", 0.7)),
    )

    mouse_controller = MouseController(config.get("automation", {}))
    keyboard_controller = KeyboardController(config.get("automation", {}))

    task_queue = TaskQueue()

    return {
        "window_manager": window_manager,
        "capture": print_window,
        "ocr_engine": ocr_engine,
        "vl_detector": vl_detector,
        "contact_detector": contact_detector,
        "message_detector": message_detector,
        "llm_provider": llm_provider,
        "mouse_controller": mouse_controller,
        "keyboard_controller": keyboard_controller,
        "task_queue": task_queue,
    }


def build_state_machine(config: dict) -> tuple:
    """组装状态机和看门狗。

    Returns:
        (components, state_machine, watchdog) 三元组。
    """
    components = build_components(config)

    state_machine = StateMachine(components, config)
    watchdog = Watchdog(
        state_machine=state_machine,
        window_manager=components["window_manager"],
        config=config.get("watchdog", {}),
    )

    return components, state_machine, watchdog

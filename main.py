"""
微信 OCR + LLM 自动回复系统
入口文件 — 组装所有组件并运行主循环
"""

import logging
import logging.handlers
import os
import signal
import sys
import time

import yaml


def setup_logging(config: dict) -> None:
    """配置日志，支持文件轮转和终端输出。

    Args:
        config: 日志配置字典。
    """
    log_dir = config.get("log_dir", "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_level = getattr(logging, config.get("level", "INFO").upper(), logging.INFO)
    max_bytes = config.get("max_bytes", 10 * 1024 * 1024)
    backup_count = config.get("backup_count", 5)

    log_file = os.path.join(log_dir, "wechat-auto.log")

    # 文件处理器（轮转）
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setLevel(log_level)
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_formatter)

    # 终端处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)

    # 根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def load_config(path: str = None) -> dict:
    """从 YAML 文件加载配置。

    Args:
        path: 配置文件路径，默认为 config/config.yaml。

    Returns:
        配置字典。
    """
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "config", "config.yaml")

    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return config


def main():
    """微信自动回复系统主入口。"""

    # 加载配置
    config = load_config()
    setup_logging(config.get("logging", {}))

    logger = logging.getLogger("main")
    logger.info("=" * 50)
    logger.info("微信自动回复系统启动中...")
    logger.info("=" * 50)

    # 清理上次运行留下的截图
    screenshot_dir = config.get("capture", {}).get("screenshot_dir", "screenshots")
    if os.path.isdir(screenshot_dir):
        cleaned = 0
        for f in os.listdir(screenshot_dir):
            fpath = os.path.join(screenshot_dir, f)
            if fpath.lower().endswith(".png") and os.path.isfile(fpath):
                try:
                    os.remove(fpath)
                    cleaned += 1
                except OSError:
                    pass
        if cleaned:
            logger.info("已清理 %d 张旧截图", cleaned)

    # --- 初始化所有组件 ---

    # 捕获层
    from capture.window_manager import WeChatWindowManager
    from capture.print_window import PrintWindowCapture

    window_manager = WeChatWindowManager(
        class_name=config.get("wechat", {}).get("class_name")
    )
    print_window = PrintWindowCapture(config.get("capture", {}))

    # OCR 层
    from ocr.rapid_ocr import OCREngine

    ocr_engine = OCREngine(config.get("ocr", {}))

    # LLM 层
    from llm.openai_provider import OpenAIProvider

    llm_config = config.get("llm", {})
    llm_provider = OpenAIProvider(llm_config) if llm_config.get("api_key") else None

    if llm_provider is None:
        logger.warning("LLM API 密钥未配置 — 回复生成已禁用")

    # 检测器
    from detector.vl_detector import VLDetector
    from detector.contact_detector import ContactDetector
    from detector.message_detector import MessageDetector

    vl_detector = VLDetector(llm_provider) if llm_provider else None
    contact_detector = ContactDetector(ocr_engine)
    message_detector = MessageDetector(ocr_engine)

    # 自动化
    from automation.mouse_controller import MouseController
    from automation.keyboard_controller import KeyboardController

    mouse_controller = MouseController(config.get("automation", {}))
    keyboard_controller = KeyboardController(config.get("automation", {}))

    # 任务队列
    from taskqueue.task_queue import TaskQueue

    task_queue = TaskQueue()

    # 状态机
    from state.state_machine import StateMachine

    components = {
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

    state_machine = StateMachine(components, config)

    # 看门狗
    from recovery.watchdog import Watchdog

    watchdog = Watchdog(
        state_machine=state_machine,
        window_manager=window_manager,
        config=config.get("watchdog", {})
    )

    # --- 信号处理 ---
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        logger.info("收到关闭信号，正在停止...")
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # --- 启动看门狗 ---
    watchdog.start()

    # --- 查找微信窗口 ---
    try:
        info = window_manager.find_wechat_window()
        logger.info(f"微信窗口已找到: {info}")
    except Exception as e:
        logger.warning(f"启动时未找到微信窗口: {e}")
        logger.info("将在状态机循环中重试...")

    # --- 主循环 ---
    logger.info("进入主循环。按 Ctrl+C 停止。")
    loop_interval = config.get("state_machine", {}).get("idle_cooldown", 0.5)

    while running:
        try:
            state_machine.run_cycle()
            time.sleep(loop_interval)
        except KeyboardInterrupt:
            logger.info("收到键盘中断")
            running = False
            break
        except Exception as e:
            logger.error(f"主循环错误: {e}", exc_info=True)
            time.sleep(1.0)

    # --- 优雅关闭 ---
    logger.info("正在关闭...")

    if watchdog.is_running():
        watchdog.stop()
        logger.info("看门狗已停止")

    logger.info("系统关闭完成")


if __name__ == "__main__":
    main()

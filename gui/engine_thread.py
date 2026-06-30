"""
后台引擎线程 — 在独立线程中运行 WeChat 自动回复状态机。

使用线程安全的数据结构与 GUI 通信：
  - 共享状态字典（带锁）
  - 日志队列（通过 GUIQueueHandler）
"""

import logging
import logging.handlers
import os
import sys
import threading
import time
from datetime import datetime
from typing import Any, Optional

import yaml

# 将项目根目录添加到 sys.path（兼容 PyInstaller）
def _get_project_root() -> str:
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_project_root = _get_project_root()
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


class EngineState:
    """引擎状态的线程安全封装。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "running": False,
            "state_machine_state": "IDLE",
            "current_contact": "",
            "queue_size": 0,
            "total_replies": 0,
            "total_errors": 0,
            "wechat_found": False,
            "window_title": "",
            "uptime_seconds": 0.0,
            "start_time": None,  # datetime
            "last_error": "",
            "contact_history": [],  # list of {"contact": str, "time": str, "reply": str}
            "log_path": "",
        }

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._state[key] = value

    def update(self, mapping: dict) -> None:
        with self._lock:
            self._state.update(mapping)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def add_reply(self, contact: str, reply: str) -> None:
        """添加一条回复记录到历史。"""
        with self._lock:
            self._state["total_replies"] += 1
            history = self._state["contact_history"]
            history.append({
                "contact": contact,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "reply": reply,
            })
            # 最多保留 500 条
            if len(history) > 500:
                history[:] = history[-500:]

    def add_error(self, error_msg: str) -> None:
        with self._lock:
            self._state["total_errors"] += 1
            self._state["last_error"] = error_msg


class EngineThread(threading.Thread):
    """在后台线程中运行状态机的引擎线程。

    用法::

        engine = EngineThread()
        engine.start_engine()
        ...
        engine.stop_engine()
        engine.join(timeout=5)
    """

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(daemon=True, name="AutoReplyEngine")
        self.config_path = config_path or os.path.join(
            _project_root, "config", "config.yaml"
        )
        self.state = EngineState()
        self._stop_event = threading.Event()
        self._paused = threading.Event()
        self._paused.set()  # 默认未暂停（但未启动）
        self._engine_started = threading.Event()

        # 组件引用（延迟初始化）
        self._components: dict = {}
        self._state_machine: Any = None
        self._watchdog: Any = None

    # ---- 公开 API ----

    def start_engine(self) -> bool:
        """启动引擎（启动线程，非阻塞）。"""
        if self.is_alive():
            return False
        self._stop_event.clear()
        self.state.set("running", True)
        self.state.set("starting", True)  # 显示"启动中..."状态
        self.state.set("start_time", datetime.now())
        self.state.set("uptime_seconds", 0.0)
        self.start()
        return True  # 立即返回，不阻塞 GUI

    def stop_engine(self) -> None:
        """请求引擎停止。"""
        self._stop_event.set()

    @property
    def is_running(self) -> bool:
        return self.state.get("running", False) and self.is_alive()

    # ---- 线程主循环 ----

    def run(self):
        """线程入口 — 加载配置、初始化组件、运行主循环。"""
        # 配置日志
        self._setup_logging()

        logger = logging.getLogger("gui.engine")
        logger.info("GUI 引擎线程启动")

        try:
            config = self._load_config()
            if config is None:
                self.state.set("running", False)
                self.state.set("starting", False)
                self.state.add_error("配置加载失败")
                self._engine_started.set()
                return

            # 初始化所有组件（同 main.py）
            self._init_components(config)
            self.state.set("starting", False)
            self._engine_started.set()

            # 信号处理
            running = True

            # 查找微信窗口
            try:
                info = self._components["window_manager"].find_wechat_window()
                self.state.set("wechat_found", True)
                self.state.set("window_title", f"HWND={info['hwnd']} {info['width']}x{info['height']}")
                logger.info(f"微信窗口已找到: {info}")
            except Exception as e:
                logger.warning(f"启动时未找到微信窗口: {e}")
                self.state.set("wechat_found", False)

            # 启动看门狗
            if self._watchdog:
                self._watchdog.start()

            # 主循环
            loop_interval = config.get("state_machine", {}).get("idle_cooldown", 0.5)
            start_time = time.time()

            while running:
                # 检查停止信号
                if self._stop_event.is_set():
                    logger.info("收到停止信号，退出引擎循环")
                    running = False
                    break

                # 更新状态
                if self._state_machine:
                    try:
                        self._state_machine.run_cycle()
                        self._sync_state_machine_state()
                    except Exception as e:
                        logger.error(f"状态机循环错误: {e}", exc_info=True)
                        self.state.add_error(str(e))
                        time.sleep(1.0)

                # 更新 uptime
                uptime = time.time() - start_time
                self.state.set("uptime_seconds", uptime)

                time.sleep(loop_interval)

            # 关闭
            if self._watchdog and self._watchdog.is_running():
                self._watchdog.stop()

            logger.info("引擎线程正常退出")

        except Exception as e:
            logger.critical(f"引擎线程未处理异常: {e}", exc_info=True)
            self.state.add_error(f"引擎崩溃: {e}")
        finally:
            self.state.set("running", False)
            self.state.set("starting", False)
            self._engine_started.set()

    # ---- 内部方法 ----

    def _setup_logging(self):
        """配置日志 — 适配已有日志系统。"""
        root_logger = logging.getLogger()
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

        # 防止重复添加 GUI handler
        has_gui_handler = any(
            isinstance(h, logging.Handler)
            and h.__class__.__module__ == "gui.log_handler"
            for h in root_logger.handlers
        )
        if not has_gui_handler:
            from gui.log_handler import GUIQueueHandler
            gui_handler = GUIQueueHandler()
            gui_handler.setLevel(logging.DEBUG)
            gui_handler.setFormatter(formatter)
            root_logger.addHandler(gui_handler)

        root_logger.setLevel(logging.DEBUG)

        # 抑制第三方库的 DEBUG 日志，仅保留核心模块的调试信息
        for noisy_logger in (
            "PIL.PngImagePlugin", "PIL.Image", "PIL.TgaImagePlugin",
            "httpx", "httpcore", "urllib3", "chardet",
        ):
            logging.getLogger(noisy_logger).setLevel(logging.WARNING)

        # 文件日志（始终添加，引擎线程独享）
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, "wechat-auto.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    def _load_config(self) -> Optional[dict]:
        """加载 YAML 配置。"""
        try:
            with open(self.config_path, encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception as e:
            logging.getLogger("gui.engine").error(f"加载配置失败: {e}")
            return None

    def _init_components(self, config: dict):
        """初始化所有组件（与 main.py 逻辑一致）。"""
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

        window_manager = WeChatWindowManager(
            class_name=config.get("wechat", {}).get("class_name")
        )
        print_window = PrintWindowCapture(config.get("capture", {}))

        ocr_engine = OCREngine(config.get("ocr", {}))

        llm_config = config.get("llm", {})
        llm_provider = OpenAIProvider(llm_config) if llm_config.get("api_key") else None

        if llm_provider is None:
            logging.getLogger("gui.engine").warning("LLM API 密钥未配置 — 回复生成已禁用")

        vl_detector = VLDetector(llm_provider) if llm_provider else None
        contact_detector = ContactDetector(ocr_engine)
        message_detector = MessageDetector(ocr_engine)

        mouse_controller = MouseController(config.get("automation", {}))
        keyboard_controller = KeyboardController(config.get("automation", {}))

        task_queue = TaskQueue()

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
        watchdog = Watchdog(
            state_machine=state_machine,
            window_manager=window_manager,
            config=config.get("watchdog", {}),
        )

        self._components = components
        self._state_machine = state_machine
        self._watchdog = watchdog

    def _sync_state_machine_state(self):
        """将状态机内部状态同步到共享 EngineState。"""
        if self._state_machine is None:
            return

        sm = self._state_machine
        current_contact = getattr(sm, '_current_contact', None)
        reply_text = getattr(sm, '_reply_text', None)
        prev_state = getattr(sm, '_prev_state', None)
        last_reply_contact = getattr(sm, '_last_reply_contact', "")
        self.state.update({
            "state_machine_state": sm.state.value if sm.state else "UNKNOWN",
            "queue_size": sm.task_queue.size(),
            "current_contact": (
                current_contact.contact_name
                if current_contact
                else ""
            ),
        })

        # 捕获 COMPLETE 状态以记录回复
        # 注意: sm.state 在 run_cycle() 后已从 COMPLETE 转换走，
        # 因此检查 _prev_state 来检测刚完成的回复。
        # 用 _last_reply_contact 取联系人名称（_current_contact 可能已被改写成下一个任务）
        if prev_state and prev_state.value == "COMPLETE":
            contact_name = last_reply_contact or "未知"
            if reply_text:
                self.state.add_reply(contact_name, reply_text)
"""微信自动回复状态机 — 核心调度器。

状态处理逻辑在 state.handlers 中通过 Mixin 注入。
"""

import enum
import logging
import time
from typing import Optional, Any

from state.handlers import StateHandlersMixin

logger = logging.getLogger(__name__)


class State(enum.Enum):
    IDLE = "IDLE"
    MONITOR = "MONITOR"
    DETECT_UNREAD = "DETECT_UNREAD"
    OPEN_CHAT = "OPEN_CHAT"
    READ_MESSAGE = "READ_MESSAGE"
    GENERATE_REPLY = "GENERATE_REPLY"
    SEND = "SEND"
    VERIFY = "VERIFY"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"


class StateMachine(StateHandlersMixin):
    """通过线性状态机驱动微信自动回复工作流。

    状态：IDLE -> MONITOR -> DETECT_UNREAD -> OPEN_CHAT -> READ_MESSAGE
          -> GENERATE_REPLY -> SEND -> VERIFY -> COMPLETE / ERROR -> IDLE

    每次调用 ``run_cycle()`` 执行当前状态的一次迭代
    并转换到下一个状态。调用者应在 ~10 Hz 循环中调用它::

        while True:
            state_machine.run_cycle()
            time.sleep(0.1)
    """

    _State = State

    def __init__(self, components: dict, config: dict = None):
        self.window_manager = components["window_manager"]
        self.capture = components["capture"]
        self.ocr_engine = components["ocr_engine"]
        self.vl_detector = components["vl_detector"]
        self.contact_detector = components["contact_detector"]
        self.message_detector = components["message_detector"]
        self.llm_provider = components["llm_provider"]
        self.mouse_controller = components["mouse_controller"]
        self.keyboard_controller = components["keyboard_controller"]
        self.task_queue = components["task_queue"]

        self.config = config or {}
        self._poll_interval = (
            self.config.get("monitor", {}).get("poll_interval", 1.0)
        )

        # 状态机账簿
        self._state: State = State.IDLE
        self._prev_state: Optional[State] = None
        self._cycle_count: int = 0
        self._retry_count: int = 0

        # 运行时数据
        self._current_contact: Any = None
        self._current_messages: list = []
        self._reply_text: Optional[str] = None
        self._error_message: Optional[str] = None
        self._last_full_image = None
        self._last_panel_hash = None
        self._phash_threshold: int = (
            self.config.get("monitor", {}).get("phash_threshold", 5)
        )
        self._last_vl_time: float = time.time()
        self._force_vl_interval: float = (
            self.config.get("monitor", {}).get("force_vl_interval", 60.0)
        )
        self._chat_cycle_count: int = 0
        self._last_reply_time: float = 0
        self._last_reply_contact: str = ""

    # ---- 公开 API -------------------------------------------------------

    @property
    def state(self) -> State:
        return self._state

    def run_cycle(self) -> None:
        """执行当前状态处理程序的一次迭代。"""
        try:
            dispatch = {
                State.IDLE: self._handle_idle,
                State.MONITOR: self._handle_monitor,
                State.DETECT_UNREAD: self._handle_detect_unread,
                State.OPEN_CHAT: self._handle_open_chat,
                State.READ_MESSAGE: self._handle_read_message,
                State.GENERATE_REPLY: self._handle_generate_reply,
                State.SEND: self._handle_send,
                State.VERIFY: self._handle_verify,
                State.COMPLETE: self._handle_complete,
                State.ERROR: self._handle_error,
            }
            handler = dispatch.get(self._state)
            if handler is not None:
                handler()
            self._cycle_count += 1
        except Exception:
            logger.exception("状态 %s 中出现未处理的异常", self._state.value)
            self._error_message = f"状态 {self._state.value} 中出现未处理的异常"
            self._transition(State.ERROR)

    # ---- 转换 -----------------------------------------------------------

    def _transition(self, target: State) -> None:
        """从当前状态移动到 *target*，重置状态内计数器。"""
        self._prev_state = self._state
        logger.info("[状态机] %s → %s", self._state.value, target.value)
        self._state = target
        self._cycle_count = 0

    # ---- 恢复 API（由看门狗调用）-----------------------------------------

    def force_recovery(self) -> None:
        """从任何状态强制错误恢复。由看门狗在检测到卡死时调用。"""
        self._error_message = f"从卡死状态 {self._state.value} 强制恢复"
        logger.warning(self._error_message)
        self._state = State.ERROR

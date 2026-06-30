import enum
import logging
import time
from typing import Optional, Callable, Any
import win32gui
import pyautogui as _pag

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


class StateMachine:
    """通过线性状态机驱动微信自动回复工作流。

    状态：IDLE -> MONITOR -> DETECT_UNREAD -> OPEN_CHAT -> READ_MESSAGE
          -> GENERATE_REPLY -> SEND -> VERIFY -> COMPLETE / ERROR -> IDLE

    每次调用 ``run_cycle()`` 执行当前状态的一次迭代
    并转换到下一个状态。调用者应在 ~10 Hz 循环中调用它::

        while True:
            state_machine.run_cycle()
            time.sleep(0.1)
    """

    def __init__(self, components: dict, config: dict = None):
        # ------------------------------------------------------------------
        # 组件引用（从外部注入 — 不直接导入）
        # ------------------------------------------------------------------
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
        # ------------------------------------------------------------------
        # 配置
        # ------------------------------------------------------------------
        self.config = config or {}
        self._poll_interval = (
            self.config.get("monitor", {}).get("poll_interval", 1.0)
        )

        # ------------------------------------------------------------------
        # 状态机账簿
        # ------------------------------------------------------------------
        self._state: State = State.IDLE
        self._prev_state: Optional[State] = None
        self._cycle_count: int = 0      # 当前状态的周期数
        self._retry_count: int = 0      # 当前操作的重试次数

        # ------------------------------------------------------------------
        # 运行时数据
        # ------------------------------------------------------------------
        self._current_contact: Any = None          # 当前任务/联系人
        self._current_messages: list = []          # LLM 上下文消息
        self._reply_text: Optional[str] = None     # 生成的回复
        self._error_message: Optional[str] = None  # 最近错误描述
        self._last_full_image = None               # 最近全屏截图
        self._chat_cycle_count: int = 0            # 当前联系人的总周期数
        self._last_reply_time: float = 0           # 最近回复的时间戳（去重用）
        self._last_reply_contact: str = ""         # 最近回复的联系人名称（去重用）

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

    # ---- 转换辅助方法 ------------------------------------------------

    def _transition(self, target: State) -> None:
        """从当前状态移动到 *target*，重置状态内计数器。"""
        self._prev_state = self._state
        logger.info("[状态机] %s → %s", self._state.value, target.value)
        self._state = target
        self._cycle_count = 0

    # ---- 公开恢复 API（由看门狗调用）-------------------------

    def force_recovery(self) -> None:
        """从任何状态强制错误恢复。由看门狗在检测到卡死时调用。"""
        self._error_message = f"从卡死状态 {self._state.value} 强制恢复"
        logger.warning(self._error_message)
        self._state = State.ERROR
        # 注意：_handle_error 将在下次 run_cycle() 时被调用，因为状态现在是 ERROR

    # ---- state handlers ---------------------------------------------------

    def _handle_idle(self) -> None:
        """验证微信是否在运行，然后进入 MONITOR 状态。"""
        try:
            info = self.window_manager.find_wechat_window()
            hwnd = info["hwnd"]
            if not self.window_manager.is_wechat_running(hwnd):
                logger.info("微信窗口已找到但无响应")
                return  # stay IDLE
        except Exception:
            logger.info("未找到微信，重试中...")
            return  # stay IDLE

        self._transition(State.MONITOR)

    def _handle_monitor(self) -> None:
        """轮询间隔后直接进入未读检测（无 phash 变化检测）。"""
        time.sleep(self._poll_interval)
        self._transition(State.DETECT_UNREAD)

    def _handle_detect_unread(self) -> None:
        """VL 识别未读联系人 → OCR 精确定位 → 入队。"""
        if self.vl_detector is None:
            self._error_message = "VL 检测器未初始化（LLM 未配置）"
            logger.error(self._error_message)
            self._transition(State.ERROR)
            return

        hwnd = self.window_manager.hwnd
        image = self.capture.capture_wechat(hwnd)
        if image is None:
            self._error_message = "DETECT_UNREAD 中截图失败"
            self._transition(State.ERROR)
            return
        self._last_full_image = image

        # 1. VL 识别哪些联系人有无读消息
        vl_contacts = self.vl_detector.find_unread_contacts(image)
        if not vl_contacts:
            logger.info("[未读检测] VL 未发现未读联系人，返回监控")
            self._transition(State.IDLE)
            return

        # 2. 用本地 OCR 精确定位每个联系人的可点击坐标
        for vc in vl_contacts:
            name = vc.get("name", "").strip()
            if not name:
                continue
            # 检查是否已在队列中
            if self.task_queue.contains(name):
                continue
            # 用 OCR 获取精确位置
            contact = self.contact_detector.find_contact_by_name(image, name)
            center = contact["center"] if contact else vc.get("contact_center", (0, 0))
            self.task_queue.enqueue(name, center, vc.get("unread_count", 1))

        task = self.task_queue.dequeue()
        if task is None:
            logger.info("[未读检测] 队列为空，返回监控")
            self._transition(State.IDLE)
            return

        # 去重：如果刚刚回复过该联系人且在冷却期内，跳过
        cooldown = self.config.get("automation", {}).get("reply_cooldown", 30)
        if (task.contact_name == self._last_reply_contact and
                time.time() - self._last_reply_time < cooldown):
            logger.info("[未读检测] 跳过 %s（回复冷却 %ds 激活中）",
                        task.contact_name, cooldown)
            self._transition(State.IDLE)
            return

        # 仅当切换联系人时重置重试计数器
        old_name = self._current_contact.contact_name if self._current_contact else None
        if task.contact_name != old_name:
            self._chat_cycle_count = 0

        self._current_contact = task
        self._transition(State.OPEN_CHAT)

    def _handle_open_chat(self) -> None:
        """在联系人列表中点击目标联系人并验证聊天已打开。"""
        if self._current_contact is None:
            self._error_message = "OPEN_CHAT 未设置当前联系人"
            self._transition(State.ERROR)
            return

        hwnd = self.window_manager.hwnd
        if not hwnd:
            self._error_message = "没有可用的微信窗口句柄"
            self._transition(State.ERROR)
            return

        # 捕获新截图用于联系人定位
        image = self.capture.capture_wechat(hwnd)
        if image is None:
            self._retry_count += 1
            if self._retry_count >= 3:
                self._error_message = "3 次重试后截图仍然失败"
                self._transition(State.ERROR)
                return
            time.sleep(1)
            return  # 留在 OPEN_CHAT

        self._last_full_image = image

        contact_pos = self.contact_detector.find_contact_by_name(
            self._last_full_image, self._current_contact.contact_name
        )
        if contact_pos is None:
            self._retry_count += 1
            logger.info("[打开会话] 第 %d 次查找联系人 %s 失败，滚动后重试",
                         self._retry_count, self._current_contact.contact_name)
            # 滚动左侧面板以显示更多联系人
            # 先将鼠标移到左侧面板，使 pyautogui.scroll 作用于正确区域
            if hwnd:
                rect = win32gui.GetWindowRect(hwnd)
                _pag.moveTo(rect[0] + 50, rect[1] + rect[3] // 2)
            self.mouse_controller.scroll_down(5)
            time.sleep(0.5)
            if self._retry_count >= 3:
                self._error_message = (
                    f"联系人 '{self._current_contact.contact_name}' "
                    f"3 次查找后仍未找到"
                )
                self._transition(State.ERROR)
                return
            time.sleep(1)
            return  # 留在 OPEN_CHAT（用新截图+滚动重试）

        self._retry_count = 0

        # 点击联系人
        clicked = self.mouse_controller.click_center(contact_pos["bbox"], hwnd)
        if not clicked:
            self._retry_count += 1
            if self._retry_count >= 3:
                self._error_message = "点击联系人失败（3 次重试后）"
                self._transition(State.ERROR)
                return
            logger.warning("[打开会话] 点击 %s 失败 (第 %d 次)，重试",
                           self._current_contact.contact_name, self._retry_count)
            time.sleep(1)
            return  # 留在 OPEN_CHAT
        time.sleep(2)  # 等待聊天面板加载

        # 通过 OCR 验证聊天标题
        fresh_image = self.capture.capture_wechat(hwnd)
        if fresh_image is None:
            self._retry_count += 1
            if self._retry_count >= 3:
                self._transition(State.ERROR)
                return
            time.sleep(1)
            return

        title_text = self.ocr_engine.ocr_region_text(
            fresh_image,
            {"left": 0.30, "top": 0.0, "width": 0.70, "height": 0.10},
        )
        if self._current_contact.contact_name not in (title_text or ""):
            self._retry_count += 1
            if self._retry_count >= 3:
                self._error_message = (
                    f"聊天标题验证失败: "
                    f"'{self._current_contact.contact_name}'"
                )
                self._transition(State.ERROR)
                return
            time.sleep(1)
            return  # 留在 OPEN_CHAT（重试）

        logger.info("[打开会话] 标题验证通过: %s", title_text)
        self._last_full_image = fresh_image
        self._transition(State.READ_MESSAGE)

    def _handle_read_message(self) -> None:
        """从聊天面板提取最近消息，截图失败最多重试 3 次。"""
        for attempt in range(3):
            hwnd = self.window_manager.hwnd
            if not hwnd:
                self._error_message = "READ_MESSAGE 没有可用的微信窗口句柄"
                self._transition(State.ERROR)
                return
            image = self.capture.capture_wechat(hwnd)
            if image is not None:
                self._last_full_image = image
                break
            time.sleep(0.5)
        else:
            self._error_message = "READ_MESSAGE 3 次重试后截图失败"
            self._transition(State.ERROR)
            return

        messages = self.message_detector.extract_messages(
            self._last_full_image, max_messages=20
        )
        logger.info("[读取消息] 提取到 %d 条消息", len(messages))
        if not messages:
            logger.warning("聊天中未提取到消息 — 跳过回复生成")
            self._current_messages = []
            self._transition(State.COMPLETE)
            return
        self._current_messages = messages
        self._transition(State.GENERATE_REPLY)

    def _handle_generate_reply(self) -> None:
        """将对话历史发送给 LLM 并存储回复。"""
        if self.llm_provider is None:
            self._error_message = "LLM 未配置 — 请在配置中设置 api_key"
            logger.error(self._error_message)
            self._transition(State.ERROR)
            return

        llm_messages = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in self._current_messages
        ]
        system_prompt = (self
                         .config.get("prompt", {}).get("system", ""))
        reply = self.llm_provider.generate_reply(llm_messages, system_prompt)

        if not reply:
            self._error_message = "LLM 返回空回复"
            self._transition(State.ERROR)
            return

        self._reply_text = reply
        logger.info("[生成回复] 生成: %s", self._reply_text[:50])
        self._transition(State.SEND)

    def _handle_send(self) -> None:
        """输入并发送生成的回复文本。"""
        hwnd = self.window_manager.hwnd
        if not hwnd:
            self._error_message = "SEND 没有可用的微信窗口句柄"
            self._transition(State.ERROR)
            return

        # 点击输入框区域（聊天面板底部居中位置）
        image = self.capture.capture_wechat(hwnd)
        if image is not None:
            self._last_full_image = image

        # 点击输入框区域
        self.mouse_controller.click_region(
            {"left": 0.30, "top": 0.85, "width": 0.70, "height": 0.15},
            hwnd,
        )
        time.sleep(0.5)

        self.keyboard_controller.clear_input()
        time.sleep(0.3)

        self.keyboard_controller.type_text(self._reply_text)
        time.sleep(0.3)

        self.keyboard_controller.press_enter()

        send_delay = self.config.get("automation", {}).get("send_delay", 1.5)
        time.sleep(send_delay)

        self._transition(State.VERIFY)
        logger.info("[发送] 回复已发送，进入验证")

    def _handle_verify(self) -> None:
        """检查发送的消息是否出现在聊天历史中。"""
        hwnd = self.window_manager.hwnd
        image = self.capture.capture_wechat(hwnd)
        if image is not None:
            self._last_full_image = image

        # 提取消息区域所有文字（不只是最后一条，防止 OCR 漏捡）
        all_msgs = self.message_detector.extract_messages(self._last_full_image, max_messages=30)

        if not all_msgs:
            self._retry_count += 1
            if self._retry_count >= 3:
                self._error_message = "3 次重试后无法验证消息发送"
                self._transition(State.ERROR)
                return
            time.sleep(0.5)
            return

        # 取最后 5 条 assistant（自己发送的）消息的内容拼接起来
        recent_assistant = " ".join(
            m["content"] for m in all_msgs[-10:] if m.get("role") == "assistant"
        )

        if self._reply_text:
            reply_clean = self._reply_text.rstrip()
            # 子串匹配：回复内容出现在最近发送的消息中即通过
            if reply_clean in (recent_assistant or ""):
                logger.info("[验证] 发送验证通过 (子串匹配)")
                self._retry_count = 0
                self._transition(State.COMPLETE)
                return

        self._retry_count += 1
        logger.warning("[验证] 发送内容不匹配 (第 %d 次) — 回复=%s, OCR捡到=%s",
                       self._retry_count, self._reply_text,
                       (recent_assistant or "")[:80])
        if self._retry_count >= 3:
            # 3 次都不匹配，但消息可能实际上已发送（OCR 不可靠），直接进 COMPLETE
            logger.warning("[验证] 3 次 OCR 验证均失败，假设发送成功")
            self._retry_count = 0
            self._transition(State.COMPLETE)
            return
        time.sleep(0.5)
        # stay VERIFY

    def _handle_complete(self) -> None:
        """记录成功日志并检查队列中是否有剩余任务。"""
        contact_name = (
            self._current_contact.contact_name
            if self._current_contact
            else "未知"
        )
        logger.info(
            "已向 %s 发送回复: %s",
            contact_name,
            self._reply_text,
        )
        # 记录回复用于去重冷却（防止立即重复回复循环）
        self._last_reply_contact = contact_name
        self._last_reply_time = time.time()

        next_task = self.task_queue.dequeue()
        if next_task is not None:
            self._current_contact = next_task
            self._chat_cycle_count = 0  # 新联系人重置重试计数器
            self._transition(State.OPEN_CHAT)
            return

        # 没有更多任务 — 返回监控
        # 注意: 先 transition 再清理，让 _sync_state_machine_state() 能读到 _reply_text
        self._transition(State.MONITOR)
        self._current_contact = None
        self._current_messages = []
        # 故意不清空 _reply_text: 供 _sync_state_machine_state() 在下个周期捕获回复记录，
        # 随后在 _handle_generate_reply() 中被覆盖，或在 _handle_error() 中被清空
        self._chat_cycle_count = 0

    def _handle_error(self) -> None:
        """记录错误信息，重置运行时状态，返回 IDLE。"""
        logger.error("状态机进入 ERROR: %s", self._error_message)

        # 重新入队当前联系人，使其不会因临时故障丢失，
        # 但如果超过 max_cycles_per_chat（可配置，默认 3）则丢弃
        max_cycles = self.config.get("state_machine", {}).get("max_cycles_per_chat", 3)
        if self._current_contact is not None:
            self._chat_cycle_count += 1
            if self._chat_cycle_count < max_cycles:
                logger.info("错误后重新入队 %s (周期 %d/%d)",
                            self._current_contact.contact_name,
                            self._chat_cycle_count, max_cycles)
                if not self.task_queue.contains(self._current_contact.contact_name):
                    self.task_queue.enqueue(
                        self._current_contact.contact_name,
                        self._current_contact.contact_center,
                        self._current_contact.unread_count,
                    )
            else:
                logger.warning("丢弃 %s（%d 次失败周期后）",
                               self._current_contact.contact_name, self._chat_cycle_count)

        # Clean up runtime data
        self._current_contact = None
        self._current_messages = []
        self._reply_text = None
        self._retry_count = 0
        self._last_full_image = None

        self._transition(State.IDLE)

"""状态处理器 — 每个状态对应一个 handle_ 方法。

这是一个 mixin 类，由 StateMachine 继承，将 500+ 行逻辑从
状态机核心中分离出来以提高可读性。
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import imagehash
import win32gui
import pyautogui as _pag

logger = logging.getLogger(__name__)


class StateHandlersMixin:
    """提供所有状态处理方法的 Mixin，由 StateMachine 继承使用。"""

    def _handle_idle(self) -> None:
        """验证微信是否在运行，然后进入 MONITOR 状态。"""
        try:
            info = self.window_manager.find_wechat_window()
            hwnd = info["hwnd"]
            if not self.window_manager.is_wechat_running(hwnd):
                logger.info("微信窗口已找到但无响应")
                return
        except Exception:
            logger.info("未找到微信，重试中...")
            return

        self._transition(self._State.MONITOR)

    def _handle_monitor(self) -> None:
        """轮询间隔后直接进入未读检测。"""
        time.sleep(self._poll_interval)
        self._transition(self._State.DETECT_UNREAD)

    def _handle_detect_unread(self) -> None:
        """VL 识别未读联系人 → OCR 精确定位 → 入队。"""
        if self.vl_detector is None:
            self._error_message = "VL 检测器未初始化（LLM 未配置）"
            logger.error(self._error_message)
            self._transition(self._State.ERROR)
            return

        hwnd = self.window_manager.hwnd
        image = self.capture.capture_wechat(hwnd)
        if image is None:
            self._error_message = "DETECT_UNREAD 中截图失败"
            self._transition(self._State.ERROR)
            return
        self._last_full_image = image

        # 快速路径：如果左侧面板没有变化且未超时，跳过昂贵的 VL 调用
        crop_cfg = self.config.get("capture", {}).get("crop_regions", {}).get("left_panel", {})
        lp_left = int(crop_cfg.get("left", 0.0) * image.width)
        lp_top = int(crop_cfg.get("top", 0.08) * image.height)
        lp_w = int(crop_cfg.get("width", 0.30) * image.width)
        lp_h = int(crop_cfg.get("height", 0.92) * image.height)
        left_panel = image.crop((lp_left, lp_top, lp_left + lp_w, lp_top + lp_h))
        current_hash = imagehash.phash(left_panel)
        time_since_vl = time.time() - self._last_vl_time
        force_vl = time_since_vl >= self._force_vl_interval
        if self._last_panel_hash is not None and not force_vl:
            diff = current_hash - self._last_panel_hash
            if diff <= self._phash_threshold:
                logger.debug("[未读检测] 左侧面板无变化 (phash diff=%d)，跳过 VL", diff)
                self._transition(self._State.IDLE)
                return
        if force_vl:
            logger.info("[未读检测] 强制 VL 检测 (距上次 %.0f 秒)", time_since_vl)

        # 并行发起 VL 识别（仅左侧面板）+ OCR 联系人定位，消除串行等待
        t0 = time.time()
        vl_failed = False
        with ThreadPoolExecutor(max_workers=2) as ex:
            vl_future = ex.submit(self.vl_detector.find_unread_contacts, left_panel)
            ocr_future = ex.submit(self.contact_detector.get_contact_positions, image)
            try:
                vl_result = vl_future.result()
            except Exception as e:
                logger.error("[未读检测] VL 调用异常: %s", e)
                vl_result = None
            try:
                ocr_contacts = ocr_future.result()
            except Exception as e:
                logger.error("[未读检测] OCR 定位异常: %s", e)
                ocr_contacts = []

        if vl_result is None:
            vl_failed = True
            vl_contacts = []
        else:
            vl_contacts = vl_result

        logger.debug("[未读检测] VL+OCR 并行耗时 %.2fs (VL=%s, OCR=%d)",
                     time.time() - t0,
                     "失败" if vl_failed else len(vl_contacts),
                     len(ocr_contacts))

        # 仅在 VL 成功时缓存 phash：LLM 超时/异常时保留旧 hash，
        # 让下一轮即使面板无变化也能重试 VL，避免漏回复未读联系人
        if not vl_failed:
            self._last_panel_hash = current_hash
            self._last_vl_time = time.time()
        else:
            logger.warning("[未读检测] VL 失败，保留旧 phash 以便下轮重试")
            # 冷却一段时间避免立即再次触发 LLM 调用，防止在故障期间形成紧循环
            time.sleep(5)
            self._transition(self._State.IDLE)
            return

        if not vl_contacts:
            logger.info("[未读检测] VL 未发现未读联系人，返回监控")
            self._transition(self._State.IDLE)
            return

        # 用一次 OCR 得到的联系人列表匹配 VL 名称，避免 N 次冗余 OCR
        ignore_list = self.config.get("automation", {}).get("ignore_contacts", []) or []
        for vc in vl_contacts:
            name = vc.get("name", "").strip()
            if not name:
                continue
            if self._is_ignored_contact(name, ignore_list):
                logger.info("[未读检测] 跳过被忽略的联系人 '%s'（命中黑名单）", name)
                continue
            if self.task_queue.contains(name):
                continue
            matched = self._match_contact(name, ocr_contacts)
            if matched is not None:
                center = matched["center"]
                bbox = matched["bbox"]
            else:
                center = (0, 0)
                bbox = None
                logger.warning("[未读检测] OCR 未匹配到 '%s'，将在 OPEN_CHAT 中重试", name)
            self.task_queue.enqueue(name, center, vc.get("unread_count", 1), contact_bbox=bbox)

        task = self.task_queue.dequeue()
        if task is None:
            logger.info("[未读检测] 队列为空，返回监控")
            self._transition(self._State.IDLE)
            return

        # 去重：如果刚刚回复过该联系人且在冷却期内，跳过
        cooldown = self.config.get("automation", {}).get("reply_cooldown", 30)
        if (task.contact_name == self._last_reply_contact and
                time.time() - self._last_reply_time < cooldown):
            logger.info("[未读检测] 跳过 %s（回复冷却 %ds 激活中）",
                        task.contact_name, cooldown)
            self._transition(self._State.IDLE)
            return

        # 仅当切换联系人时重置重试计数器
        old_name = self._current_contact.contact_name if self._current_contact else None
        if task.contact_name != old_name:
            self._chat_cycle_count = 0

        self._current_contact = task
        self._transition(self._State.OPEN_CHAT)

    @staticmethod
    def _match_contact(target_name: str, ocr_contacts: list) -> Any:
        """按名称从已有 OCR 结果里匹配联系人，避免重复调用 OCR。"""
        import re
        def _strip(s: str) -> str:
            return re.sub(r'[^\w\s\u4e00-\u9fff]', '', s or '').lower()

        target = _strip(target_name)
        if not target:
            return None
        for c in ocr_contacts:
            name_clean = _strip(c.get('name', ''))
            if not name_clean:
                continue
            if target in name_clean or name_clean in target:
                return c
        return None

    @staticmethod
    def _is_ignored_contact(name: str, ignore_list: list) -> bool:
        """判断联系人名是否命中黑名单子串（不区分大小写）。"""
        if not name or not ignore_list:
            return False
        lo = name.lower()
        for kw in ignore_list:
            if not kw:
                continue
            if str(kw).strip().lower() in lo:
                return True
        return False

    def _handle_open_chat(self) -> None:
        """在联系人列表中点击目标联系人并验证聊天已打开。"""
        if self._current_contact is None:
            self._error_message = "OPEN_CHAT 未设置当前联系人"
            self._transition(self._State.ERROR)
            return

        hwnd = self.window_manager.hwnd
        if not hwnd:
            self._error_message = "没有可用的微信窗口句柄"
            self._transition(self._State.ERROR)
            return

        cached_bbox = self._current_contact.contact_bbox
        if cached_bbox and self._retry_count == 0:
            # 复用 DETECT_UNREAD 阶段 OCR 得到的坐标，省一次截图+OCR
            logger.info("[打开会话] 使用缓存坐标点击 %s bbox=%s",
                        self._current_contact.contact_name, cached_bbox)
            clicked = self.mouse_controller.click_center(cached_bbox, hwnd)
            if not clicked:
                # 缓存坐标点击失败，回退到重新定位（下一轮 _retry_count>0 走原路径）
                self._retry_count += 1
                self._current_contact.contact_bbox = None
                logger.warning("[打开会话] 缓存坐标点击失败，回退到重新定位")
                time.sleep(1)
                return
            # click_at 已包含 post_click_delay，无需重复等待
        else:
            image = self.capture.capture_wechat(hwnd)
            if image is None:
                self._retry_count += 1
                if self._retry_count >= 3:
                    self._error_message = "3 次重试后截图仍然失败"
                    self._transition(self._State.ERROR)
                    return
                time.sleep(1)
                return

            self._last_full_image = image

            contact_pos = self.contact_detector.find_contact_by_name(
                self._last_full_image, self._current_contact.contact_name
            )
            if contact_pos is None:
                self._retry_count += 1
                logger.info("[打开会话] 第 %d 次查找联系人 %s 失败，滚动后重试",
                             self._retry_count, self._current_contact.contact_name)
                if hwnd:
                    client_rect = win32gui.GetClientRect(hwnd)
                    client_h = client_rect[3]
                    screen_x, screen_y = win32gui.ClientToScreen(hwnd, (50, client_h // 2))
                    _pag.moveTo(screen_x, screen_y)
                self.mouse_controller.scroll_down(5)
                time.sleep(0.5)
                if self._retry_count >= 3:
                    self._error_message = (
                        f"联系人 '{self._current_contact.contact_name}' "
                        f"3 次查找后仍未找到"
                    )
                    self._transition(self._State.ERROR)
                    return
                time.sleep(1)
                return

            clicked = self.mouse_controller.click_center(contact_pos["bbox"], hwnd)
            if not clicked:
                self._retry_count += 1
                if self._retry_count >= 3:
                    self._error_message = "点击联系人失败（3 次重试后）"
                    self._transition(self._State.ERROR)
                    return
                logger.warning("[打开会话] 点击 %s 失败 (第 %d 次)，重试",
                               self._current_contact.contact_name, self._retry_count)
                time.sleep(1)
                return
            # click_at 已包含 post_click_delay，无需重复等待

        self._retry_count = 0

        # 通过 OCR 验证聊天标题
        self.capture.invalidate_cache()
        fresh_image = self.capture.capture_wechat(hwnd)
        if fresh_image is None:
            self._retry_count += 1
            if self._retry_count >= 3:
                self._transition(self._State.ERROR)
                return
            time.sleep(1)
            return

        title_region = self.config.get("capture", {}).get("crop_regions", {}).get(
            "chat_title", {"left": 0.30, "top": 0.0, "width": 0.70, "height": 0.10}
        )
        title_text = self.ocr_engine.ocr_region_text(fresh_image, title_region)
        if self._current_contact.contact_name not in (title_text or ""):
            self._retry_count += 1
            # 标题不匹配说明缓存 bbox 失效，清掉让下次走完整路径
            self._current_contact.contact_bbox = None
            if self._retry_count >= 3:
                self._error_message = (
                    f"聊天标题验证失败: "
                    f"'{self._current_contact.contact_name}'"
                )
                self._transition(self._State.ERROR)
                return
            time.sleep(1)
            return

        logger.info("[打开会话] 标题验证通过: %s", title_text)
        self._last_full_image = fresh_image
        self._transition(self._State.READ_MESSAGE)

    def _handle_read_message(self) -> None:
        """从聊天面板提取最近消息，截图失败最多重试 3 次。"""
        for attempt in range(3):
            hwnd = self.window_manager.hwnd
            if not hwnd:
                self._error_message = "READ_MESSAGE 没有可用的微信窗口句柄"
                self._transition(self._State.ERROR)
                return
            image = self.capture.capture_wechat(hwnd)
            if image is not None:
                self._last_full_image = image
                break
            time.sleep(0.5)
        else:
            self._error_message = "READ_MESSAGE 3 次重试后截图失败"
            self._transition(self._State.ERROR)
            return

        messages = self.message_detector.extract_messages(
            self._last_full_image, max_messages=20
        )
        logger.info("[读取消息] 提取到 %d 条消息", len(messages))
        for i, msg in enumerate(messages, 1):
            logger.info("  #%d [%s] %s", i, msg.get("role", "?"), msg.get("content", ""))
        if not messages:
            logger.warning("聊天中未提取到消息 — 跳过回复生成")
            self._current_messages = []
            self._transition(self._State.COMPLETE)
            return
        self._current_messages = messages
        self._transition(self._State.GENERATE_REPLY)

    def _handle_generate_reply(self) -> None:
        """将对话历史发送给 LLM 并存储回复。"""
        if self.llm_provider is None:
            self._error_message = "LLM 未配置 — 请在配置中设置 api_key"
            logger.error(self._error_message)
            self._transition(self._State.ERROR)
            return

        llm_messages = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in self._current_messages
        ]
        system_prompt = self.config.get("prompt", {}).get("system", "")
        logger.info("[生成回复] 送入 LLM: system_prompt=%d 字符, 对话 %d 条",
                    len(system_prompt), len(llm_messages))
        for i, msg in enumerate(llm_messages, 1):
            logger.info("  → #%d [%s] %s", i, msg["role"], msg["content"])
        reply = self.llm_provider.generate_reply(llm_messages, system_prompt)

        if not reply:
            self._error_message = "LLM 返回空回复"
            self._transition(self._State.ERROR)
            return

        self._reply_text = reply
        logger.info("[生成回复] 生成: %s", self._reply_text)
        self._transition(self._State.SEND)

    def _handle_send(self) -> None:
        """输入并发送生成的回复文本。"""
        hwnd = self.window_manager.hwnd
        if not hwnd:
            self._error_message = "SEND 没有可用的微信窗口句柄"
            self._transition(self._State.ERROR)
            return

        image = self.capture.capture_wechat(hwnd)
        if image is not None:
            self._last_full_image = image

        input_region = self.config.get("capture", {}).get("crop_regions", {}).get(
            "input_area", {"left": 0.30, "top": 0.85, "width": 0.70, "height": 0.15}
        )
        # 每个控制器方法内部已包含相应的操作完成等待，无需重复 sleep
        self.mouse_controller.click_region(input_region, hwnd)
        self.keyboard_controller.clear_input()
        self.keyboard_controller.type_text(self._reply_text)
        self.keyboard_controller.press_enter()

        self._transition(self._State.VERIFY)
        logger.info("[发送] 回复已发送，进入验证")

    def _handle_verify(self) -> None:
        """检查发送的消息是否出现在聊天历史中。"""
        hwnd = self.window_manager.hwnd
        self.capture.invalidate_cache()
        image = self.capture.capture_wechat(hwnd)
        if image is not None:
            self._last_full_image = image

        if self._last_full_image is None:
            self._retry_count += 1
            if self._retry_count >= 3:
                self._error_message = "3 次重试后无法验证消息发送"
                self._transition(self._State.ERROR)
                return
            time.sleep(0.5)
            return

        msg_region = self.config.get("capture", {}).get("crop_regions", {}).get(
            "message_area", {"left": 0.30, "top": 0.10, "width": 0.70, "height": 0.75}
        )
        area_text = self.ocr_engine.ocr_region_text(self._last_full_image, msg_region)

        if not area_text:
            self._retry_count += 1
            if self._retry_count >= 3:
                self._error_message = "3 次重试后无法验证消息发送"
                self._transition(self._State.ERROR)
                return
            time.sleep(0.5)
            return

        if self._reply_text:
            reply_clean = self._reply_text.rstrip()
            if reply_clean in area_text:
                logger.info("[验证] 发送验证通过 (子串匹配)")
                self._retry_count = 0
                self._transition(self._State.COMPLETE)
                return

        self._retry_count += 1
        logger.warning("[验证] 发送内容不匹配 (第 %d 次)", self._retry_count)
        if self._retry_count >= 3:
            logger.warning("[验证] 3 次 OCR 验证均失败，假设发送成功")
            self._retry_count = 0
            self._transition(self._State.COMPLETE)
            return
        time.sleep(0.5)

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
        self._last_reply_contact = contact_name
        self._last_reply_time = time.time()

        next_task = self.task_queue.dequeue()
        if next_task is not None:
            self._current_contact = next_task
            self._chat_cycle_count = 0
            self._transition(self._State.OPEN_CHAT)
            return

        self._transition(self._State.MONITOR)
        self._current_contact = None
        self._current_messages = []
        self._chat_cycle_count = 0

    def _handle_error(self) -> None:
        """记录错误信息，重置运行时状态，返回 IDLE。"""
        logger.error("状态机进入 ERROR: %s", self._error_message)

        max_cycles = self.config.get("state_machine", {}).get("max_cycles_per_chat", 3)
        if self._current_contact is not None:
            self._chat_cycle_count += 1
            if self._chat_cycle_count < max_cycles:
                logger.info("错误后重新入队 %s (周期 %d/%d)",
                            self._current_contact.contact_name,
                            self._chat_cycle_count, max_cycles)
                if not self.task_queue.contains(self._current_contact.contact_name):
                    # 错误恢复时不复用 bbox，让 OPEN_CHAT 重新定位以应对界面变化
                    self.task_queue.enqueue(
                        self._current_contact.contact_name,
                        self._current_contact.contact_center,
                        self._current_contact.unread_count,
                    )
            else:
                logger.warning("丢弃 %s（%d 次失败周期后）",
                               self._current_contact.contact_name, self._chat_cycle_count)

        self._current_contact = None
        self._current_messages = []
        self._reply_text = None
        self._retry_count = 0
        self._last_full_image = None

        self._transition(self._State.IDLE)

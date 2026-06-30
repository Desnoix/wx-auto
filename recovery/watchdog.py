"""
微信自动回复系统看门狗。
监控微信进程健康、状态机活跃性和磁盘使用。
"""

import logging
import os
import subprocess
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


class Watchdog:
    """监控系统健康状态的后台看门狗。"""

    def __init__(self, state_machine, window_manager, config: Optional[dict] = None):
        """初始化看门狗。

        Args:
            state_machine: 要监控的 StateMachine 实例。
            window_manager: 用于检查窗口的 WeChatWindowManager 实例。
            config: 看门狗配置字典。
        """
        self._state_machine = state_machine
        self._window_manager = window_manager
        self._config = config or {}

        self._poll_interval = self._config.get("poll_interval", 5.0)
        self._process_name = self._config.get("wechat_process_name", "WeChat.exe")
        self._wechat_exe_path = self._config.get("wechat_exe_path", "")
        self._max_stuck_cycles = self._config.get("max_stuck_cycles", 10)
        self._max_screenshot_mb = self._config.get("max_screenshot_mb", 500)
        # screenshot_dir comes from the global capture config, passed at init
        self._screenshot_dir = self._config.get("screenshot_dir", "screenshots")

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_state = None
        self._stuck_count = 0

    def start(self) -> bool:
        """启动看门狗后台线程。"""
        if self._running:
            return False
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("看门狗已启动")
        return True

    def stop(self):
        """停止看门狗。"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        logger.info("看门狗已停止")

    def is_running(self) -> bool:
        return self._running

    def _run_loop(self):
        """看门狗主循环。"""
        while self._running:
            try:
                self._check_wechat_alive()
                self._check_state_machine_stuck()
                self._check_disk_usage()
            except Exception as e:
                logger.error(f"看门狗检查错误: {e}")
            time.sleep(self._poll_interval)

    def _check_wechat_alive(self):
        """检查微信进程是否在运行，窗口是否有效。"""
        hwnd = self._window_manager.hwnd
        if hwnd and self._window_manager.is_wechat_running(hwnd):
            return  # 微信正常运行

        # 尝试重新获取窗口句柄
        try:
            info = self._window_manager.refresh_hwnd()
            if info and info.get("hwnd"):
                logger.info("通过 refresh_hwnd() 重新获取到微信窗口")
                return
        except Exception:
            pass

        # 未找到微信 — 尝试重启
        logger.warning("未找到微信窗口，尝试重启...")
        self._restart_wechat()

    def _restart_wechat(self) -> bool:
        """尝试重启微信进程。

        Returns:
            成功启动返回 True。
        """
        if not self._wechat_exe_path:
            # 尝试常见安装路径
            candidates = [
                os.path.expandvars(r"%ProgramFiles%\Tencent\WeChat\WeChat.exe"),
                os.path.expandvars(r"%ProgramFiles(x86)%\Tencent\WeChat\WeChat.exe"),
            ]
            for path in candidates:
                if os.path.isfile(path):
                    self._wechat_exe_path = path
                    break

        if not self._wechat_exe_path or not os.path.isfile(self._wechat_exe_path):
            logger.error("无法重启微信：配置或常见路径中未找到可执行文件")
            return False

        try:
            subprocess.Popen([self._wechat_exe_path], shell=True)
            logger.info(f"微信重启已启动: {self._wechat_exe_path}")
            # 等待窗口出现
            time.sleep(3)
            # 尝试重新获取句柄
            for attempt in range(5):
                try:
                    info = self._window_manager.refresh_hwnd()
                    if info and info.get("hwnd"):
                        logger.info("重启后重新获取到微信窗口")
                        return True
                except Exception:
                    pass
                time.sleep(2)
            logger.warning("重启后未找到微信窗口（可能需要登录）")
            return False
        except Exception as e:
            logger.error(f"重启微信失败: {e}")
            return False

    def _check_state_machine_stuck(self):
        """检测状态机是否卡在相同状态。
        
        排除 IDLE 和 MONITOR 等轮询等待状态（正常工作时会反复经过这些状态），
        仅对活跃工作状态进行卡死检测：DETECT_UNREAD, OPEN_CHAT, READ_MESSAGE,
        GENERATE_REPLY, SEND, VERIFY, COMPLETE, ERROR。
        """
        current_state = self._state_machine.state
        # IDLE 和 MONITOR 是正常的等待/轮询状态，不计入卡死
        if current_state.value in ("IDLE", "MONITOR"):
            self._stuck_count = 0
            self._last_state = current_state
            return

        if current_state == self._last_state:
            self._stuck_count += 1
            logger.debug("[看门狗] 状态 %s 持续 (第 %d 次)", current_state, self._stuck_count)
        else:
            if self._last_state is not None:
                logger.info("[看门狗] 状态变化: %s → %s", self._last_state, current_state)
            self._stuck_count = 0
            self._last_state = current_state

        if self._stuck_count >= self._max_stuck_cycles:
            logger.warning(
                f"状态机在 {current_state} 卡住了 {self._stuck_count} 个周期，强制恢复"
            )
            self._state_machine.force_recovery()
            self._stuck_count = 0

    def _check_disk_usage(self):
        """截图超出限制时清理旧文件。"""
        screenshot_dir = self._screenshot_dir
        if not os.path.isdir(screenshot_dir):
            return

        total_size = 0
        files = []
        for f in os.listdir(screenshot_dir):
            fpath = os.path.join(screenshot_dir, f)
            if os.path.isfile(fpath) and f.lower().endswith(".png"):
                size = os.path.getsize(fpath)
                total_size += size
                files.append((fpath, os.path.getmtime(fpath), size))

        max_bytes = self._max_screenshot_mb * 1024 * 1024
        if total_size <= max_bytes:
            return

        # 从旧到新排序，删除最旧的文件
        files.sort(key=lambda x: x[1])  # 按修改时间排序
        for fpath, _, _ in files:
            if total_size <= max_bytes:
                break
            try:
                size = os.path.getsize(fpath)
                os.remove(fpath)
                total_size -= size
                logger.debug(f"已清理旧截图: {fpath}")
            except OSError as e:
                logger.warning(f"删除 {fpath} 失败: {e}")
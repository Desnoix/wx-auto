"""
主应用程序窗口 — customtkinter 多标签 GUI 客户端。

包含：
  - 顶部标签页切换
  - 实时状态更新（～500ms 间隔）
  - 5 个面板标签页
"""

import logging
import os
import sys
from typing import Optional

import customtkinter as ctk

from .engine_thread import EngineThread
from .log_handler import GUIQueueHandler
from .panels.dashboard import DashboardPanel
from .panels.log_viewer import LogViewerPanel
from .panels.config_panel import ConfigPanel
from .panels.screenshot_viewer import ScreenshotViewerPanel
from .panels.contact_history import ContactHistoryPanel

logger = logging.getLogger(__name__)

# 项目根目录（兼容 PyInstaller）
def _get_project_root() -> str:
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PROJECT_ROOT = _get_project_root()


class WeChatAutoGuiApp(ctk.CTk):
    """主应用程序窗口。"""

    APP_TITLE = "WeChat Auto-Reply 微信自动回复系统"
    APP_MIN_WIDTH = 900
    APP_MIN_HEIGHT = 600
    DEFAULT_SIZE = "1100x720"

    def __init__(self):
        super().__init__()
        self._refresh_counter = 0

        # 窗口配置
        self.title(self.APP_TITLE)
        self.geometry(self.DEFAULT_SIZE)
        self.minsize(self.APP_MIN_WIDTH, self.APP_MIN_HEIGHT)

        # 关闭时清理
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # 配置路径
        self._config_path = os.path.join(_PROJECT_ROOT, "config", "config.yaml")
        self._screenshot_dir = os.path.join(_PROJECT_ROOT, "screenshots")

        # 引擎线程
        self._engine: Optional[EngineThread] = None

        # 设置 logging handler（必须先于引擎启动）
        self._gui_handler = GUIQueueHandler()
        self._gui_handler.setLevel(logging.DEBUG)
        self._gui_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        # 注意：不添加到 root logger（引擎线程自己做）

        # 临时日志记录
        self._app_logger = logging.getLogger("gui.app")

        # 构建界面
        self._build_ui()

        # 启动定期刷新
        self._refresh_interval = 500  # ms
        self._schedule_refresh()

        # 将 GUI handler 挂载到 root logger（引擎启动前）
        root_logger = logging.getLogger()
        root_logger.addHandler(self._gui_handler)

    # ---- 界面构建 ----

    def _build_ui(self):
        """构建主界面。"""
        # 主标签页
        self._tab_view = ctk.CTkTabview(self, corner_radius=8)
        self._tab_view.pack(fill="both", expand=True, padx=8, pady=8)

        # 各标签页
        tab_dashboard = self._tab_view.add("📊 仪表盘")
        tab_logs = self._tab_view.add("📋 日志")
        tab_config = self._tab_view.add("⚙ 配置")
        tab_screenshots = self._tab_view.add("🖼 截图")
        tab_history = self._tab_view.add("📜 历史")

        # 仪表盘
        self._dashboard = DashboardPanel(
            tab_dashboard,
            engine_state=self._engine.state if self._engine else None,
            on_start=self._start_engine,
            on_stop=self._stop_engine,
            on_reload=self._reload_config,
        )
        self._dashboard.pack(fill="both", expand=True)

        # 日志查看器
        self._log_viewer = LogViewerPanel(tab_logs, log_handler=self._gui_handler)
        self._log_viewer.pack(fill="both", expand=True)

        # 配置编辑器
        self._config_panel = ConfigPanel(tab_config, config_path=self._config_path)
        self._config_panel.pack(fill="both", expand=True)

        # 截图查看器
        self._screenshot_viewer = ScreenshotViewerPanel(
            tab_screenshots, screenshot_dir=self._screenshot_dir
        )
        self._screenshot_viewer.pack(fill="both", expand=True)

        # 联系历史
        self._history_panel = ContactHistoryPanel(
            tab_history, engine_state=self._engine.state if self._engine else None,
        )
        self._history_panel.pack(fill="both", expand=True)

    # ---- 引擎控制 ----

    def _start_engine(self):
        """启动后台引擎（非阻塞）。"""
        if self._engine and self._engine.is_alive():
            self._app_logger.warning("引擎已在运行")
            return

        self._engine = EngineThread(config_path=self._config_path)

        # 将 engine.state 连接到面板
        self._dashboard.engine_state = self._engine.state
        self._history_panel.engine_state = self._engine.state

        if self._engine.start_engine():
            self._app_logger.info("引擎正在启动...")
            self._dashboard.set_controls_starting()
        else:
            self._app_logger.error("引擎启动失败")

    def _stop_engine(self):
        """停止后台引擎（非阻塞）。"""
        if self._engine and self._engine.is_alive():
            self._app_logger.info("正在停止引擎...")
            self._engine.stop_engine()
            self._dashboard.set_controls_stopping()
            # 使用 after 轮询引擎是否已停止
            self._poll_engine_stop()
        else:
            self._app_logger.warning("引擎未运行")

    def _poll_engine_stop(self):
        """轮询引擎是否已停止（非阻塞）。"""
        if not self.winfo_exists():
            return
        if self._engine and self._engine.is_alive():
            self.after(200, self._poll_engine_stop)
        else:
            self._app_logger.info("引擎已停止")
            self._dashboard.set_controls_running(False)

    def _reload_config(self):
        """重载配置（通过配置面板）。"""
        self._config_panel.reload_config()
        self._app_logger.info("配置已重新加载")

    # ---- 定期刷新 ----

    def _schedule_refresh(self):
        """安排定期刷新。"""
        if not self.winfo_exists():
            return
        try:
            self._refresh_all()
        except Exception as e:
            self._app_logger.warning(f"刷新面板异常: {e}")
        self.after(self._refresh_interval, self._schedule_refresh)

    def _refresh_all(self):
        """刷新所有面板。"""
        # 仪表盘总是刷新（处理 None engine_state 的空状态）
        self._dashboard.refresh()
        self._history_panel.refresh()
        self._log_viewer.refresh()
        # 截图面板每 30 次刷新一次（~15 秒间隔）
        self._refresh_counter += 1
        if self._refresh_counter >= 30:
            self._refresh_counter = 0
            self._screenshot_viewer.refresh()

    # ---- 关闭 ----

    def _on_close(self):
        """窗口关闭时的清理操作。"""
        # 非阻塞停止引擎（daemon 线程会在进程退出时清理）
        if self._engine and self._engine.is_alive():
            self._app_logger.info("正在停止引擎...")
            self._engine.stop_engine()
        self.destroy()


def run_gui():
    """启动 GUI 应用程序。"""
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    app = WeChatAutoGuiApp()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
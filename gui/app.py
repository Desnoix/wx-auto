"""
主应用程序窗口 — 现代化侧边栏 + 顶部状态栏 + 内容区布局。

设计要点：
  - Light / Dark 双主题（可运行时切换，侧边栏底部）
  - 左侧固定导航（Linear/VSCode 风格）
  - 顶部粘性 header：页面标题 · 全局引擎状态胶囊 · 引擎控制
  - 内容区面板堆叠（tkraise 切换，避免重建）
"""

import logging
import os
import sys
from typing import Optional

import customtkinter as ctk

# 兼容两种启动方式：`python main.py`（package 上下文）与 `python gui/app.py`（脚本方式）
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from gui.engine_thread import EngineThread
    from gui.log_handler import GUIQueueHandler
    from gui.panels.dashboard import DashboardPanel
    from gui.panels.log_viewer import LogViewerPanel
    from gui.panels.config_panel import ConfigPanel
    from gui.panels.screenshot_viewer import ScreenshotViewerPanel
    from gui.panels.contact_history import ContactHistoryPanel
    from gui.theme import c, set_mode, current_mode
else:
    from .engine_thread import EngineThread
    from .log_handler import GUIQueueHandler
    from .panels.dashboard import DashboardPanel
    from .panels.log_viewer import LogViewerPanel
    from .panels.config_panel import ConfigPanel
    from .panels.screenshot_viewer import ScreenshotViewerPanel
    from .panels.contact_history import ContactHistoryPanel
    from .theme import c, set_mode, current_mode


logger = logging.getLogger(__name__)


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if getattr(sys, 'frozen', False):
    _PROJECT_ROOT = sys._MEIPASS


class WeChatAutoGuiApp(ctk.CTk):
    """主应用程序窗口。"""

    APP_TITLE = "WeChat Auto-Reply"
    APP_MIN_WIDTH = 1080
    APP_MIN_HEIGHT = 720
    DEFAULT_SIZE = "1320x860"

    # (key, 图标, 标签)
    NAV_ITEMS = [
        ("dashboard", "◈", "概览"),
        ("logs",      "≡", "日志"),
        ("config",    "⚙", "配置"),
        ("shots",     "▣", "截图"),
        ("history",   "◷", "历史"),
    ]

    def __init__(self):
        super().__init__(fg_color=c("bg"))
        self._refresh_counter = 0
        self._current_nav: Optional[str] = None

        # 窗口配置
        self.title(self.APP_TITLE)
        self.geometry(self.DEFAULT_SIZE)
        self.minsize(self.APP_MIN_WIDTH, self.APP_MIN_HEIGHT)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # 路径
        self._config_path = os.path.join(_PROJECT_ROOT, "config", "config.yaml")
        self._screenshot_dir = os.path.join(_PROJECT_ROOT, "screenshots")

        # 引擎
        self._engine: Optional[EngineThread] = None

        # 日志 handler
        self._gui_handler = GUIQueueHandler()
        self._gui_handler.setLevel(logging.DEBUG)
        self._gui_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))
        self._app_logger = logging.getLogger("gui.app")

        # 构建布局
        self._build_layout()

        # 默认选中概览
        self._select_nav("dashboard")

        # 定期刷新
        self._refresh_interval = 500
        self._schedule_refresh()

        # 挂载日志到 root
        logging.getLogger().addHandler(self._gui_handler)

    # ---- 布局 ----

    def _build_layout(self):
        """构建应用外壳：左侧栏 + 右侧（header + 内容）。"""
        self.grid_columnconfigure(0, minsize=220, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # 左侧栏
        self._sidebar = self._build_sidebar()
        self._sidebar.grid(row=0, column=0, sticky="nsew")

        # 右侧主区
        main = ctk.CTkFrame(self, fg_color=c("bg"), corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        # Header
        header = self._build_header(main)
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))

        # 内容区容器
        self._content = ctk.CTkFrame(main, fg_color=c("bg"), corner_radius=0)
        self._content.grid(row=1, column=0, sticky="nsew", padx=18, pady=(6, 16))

        # 实例化并层叠所有面板
        self._panels: dict[str, ctk.CTkFrame] = {}

        self._panels["dashboard"] = DashboardPanel(
            self._content,
            engine_state=None,
            log_handler=self._gui_handler,
        )
        self._panels["logs"] = LogViewerPanel(
            self._content, log_handler=self._gui_handler,
        )
        self._panels["config"] = ConfigPanel(
            self._content, config_path=self._config_path,
        )
        self._panels["shots"] = ScreenshotViewerPanel(
            self._content, screenshot_dir=self._screenshot_dir,
        )
        self._panels["history"] = ContactHistoryPanel(
            self._content, engine_state=None,
        )

        for panel in self._panels.values():
            panel.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _build_sidebar(self) -> ctk.CTkFrame:
        sb = ctk.CTkFrame(self, width=220, fg_color=c("sidebar_bg"), corner_radius=0)
        sb.grid_propagate(False)

        # Brand
        brand = ctk.CTkFrame(sb, fg_color="transparent")
        brand.pack(fill="x", padx=20, pady=(22, 18))

        title_row = ctk.CTkFrame(brand, fg_color="transparent")
        title_row.pack(fill="x")
        ctk.CTkLabel(
            title_row, text="◆", font=ctk.CTkFont(size=18),
            text_color=c("accent"),
        ).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(
            title_row, text="WeChat Auto",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=c("text_hi"),
        ).pack(side="left")

        ctk.CTkLabel(
            brand, text="智能自动回复",
            font=ctk.CTkFont(size=11), text_color=c("text_low"),
        ).pack(anchor="w", pady=(2, 0))

        # 分隔线
        ctk.CTkFrame(sb, height=1, fg_color=c("border")).pack(
            fill="x", padx=14, pady=(4, 10),
        )

        # 导航区标题
        ctk.CTkLabel(
            sb, text="导航",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=c("text_low"), anchor="w",
        ).pack(fill="x", padx=22, pady=(2, 6))

        # 导航按钮
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        for key, icon, label in self.NAV_ITEMS:
            btn = ctk.CTkButton(
                sb, text=f"  {icon}    {label}",
                anchor="w", height=38, corner_radius=8,
                fg_color="transparent", hover_color=c("surface_2"),
                text_color=c("text_med"),
                font=ctk.CTkFont(size=13),
                command=lambda k=key: self._select_nav(k),
            )
            btn.pack(fill="x", padx=12, pady=2)
            self._nav_buttons[key] = btn

        # 底部：主题切换 + 版本
        footer = ctk.CTkFrame(sb, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=16, pady=(0, 14))

        # 主题分割线
        ctk.CTkFrame(sb, height=1, fg_color=c("border")).pack(
            side="bottom", fill="x", padx=14, pady=(6, 10),
        )

        # 版本
        ctk.CTkLabel(
            footer, text="v1.0 · Python 3.11",
            font=ctk.CTkFont(size=10), text_color=c("text_low"),
        ).pack(anchor="w", pady=(6, 0))

        # 主题切换（segmented button）
        theme_row = ctk.CTkFrame(footer, fg_color="transparent")
        theme_row.pack(fill="x", pady=(8, 0))

        ctk.CTkLabel(
            theme_row, text="主题",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=c("text_low"),
        ).pack(side="left", padx=(2, 8))

        self._theme_var = ctk.StringVar(value="深色" if current_mode() == "dark" else "浅色")
        self._theme_seg = ctk.CTkSegmentedButton(
            theme_row,
            values=["浅色", "深色"],
            variable=self._theme_var,
            command=self._on_theme_changed,
            height=26,
            selected_color=c("accent"),
            selected_hover_color=c("accent_hov"),
            unselected_color=c("surface_2"),
            unselected_hover_color=c("border_strong"),
            text_color=c("text_hi"),
            font=ctk.CTkFont(size=11),
        )
        self._theme_seg.pack(side="left", fill="x", expand=True)

        return sb

    def _build_header(self, parent) -> ctk.CTkFrame:
        hdr = ctk.CTkFrame(parent, height=56, fg_color=c("surface"), corner_radius=12)
        hdr.pack_propagate(False)

        # 页面标题
        self._page_title = ctk.CTkLabel(
            hdr, text="概览",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=c("text_hi"),
        )
        self._page_title.pack(side="left", padx=(20, 10))

        # 垂直分割线
        ctk.CTkFrame(hdr, width=1, height=24, fg_color=c("border")).pack(
            side="left", padx=8, pady=16,
        )

        # 状态胶囊
        self._status_pill = ctk.CTkFrame(
            hdr, corner_radius=999, fg_color=c("surface_2"), height=30,
        )
        self._status_pill.pack(side="left", padx=10, pady=13)
        self._status_pill.pack_propagate(False)

        self._status_light = ctk.CTkLabel(
            self._status_pill, text="●",
            font=ctk.CTkFont(size=13), text_color=c("text_low"),
        )
        self._status_light.pack(side="left", padx=(14, 6))

        self._status_text = ctk.CTkLabel(
            self._status_pill, text="引擎未启动",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=c("text_med"),
        )
        self._status_text.pack(side="left", padx=(0, 16))

        # 右侧操作
        self._start_btn = ctk.CTkButton(
            hdr, text="▶  启动", width=90, height=34, corner_radius=8,
            fg_color=c("accent"), hover_color=c("accent_hov"),
            text_color=c("accent_text"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._start_engine,
        )
        self._start_btn.pack(side="right", padx=(4, 18), pady=11)

        self._stop_btn = ctk.CTkButton(
            hdr, text="■  停止", width=90, height=34, corner_radius=8,
            fg_color=c("error_bg"), hover_color=c("error_hov"),
            text_color=c("error_text"),
            state="disabled", command=self._stop_engine,
        )
        self._stop_btn.pack(side="right", padx=4, pady=11)

        self._reload_btn = ctk.CTkButton(
            hdr, text="⟳  重载", width=90, height=34, corner_radius=8,
            fg_color="transparent", border_width=1, border_color=c("border"),
            text_color=c("text_med"), hover_color=c("surface_2"),
            command=self._reload_config,
        )
        self._reload_btn.pack(side="right", padx=4, pady=11)

        return hdr

    # ---- 导航 ----

    def _select_nav(self, key: str):
        if key == self._current_nav:
            return
        self._current_nav = key

        for k, btn in self._nav_buttons.items():
            if k == key:
                btn.configure(
                    fg_color=c("surface_2"), text_color=c("text_hi"),
                    font=ctk.CTkFont(size=13, weight="bold"),
                )
            else:
                btn.configure(
                    fg_color="transparent", text_color=c("text_med"),
                    font=ctk.CTkFont(size=13),
                )

        self._panels[key].tkraise()

        # 更新页面标题
        for k, _, label in self.NAV_ITEMS:
            if k == key:
                self._page_title.configure(text=label)
                break

    # ---- 主题 ----

    def _on_theme_changed(self, value: str):
        mode = "light" if value == "浅色" else "dark"
        set_mode(mode)
        # 重绘导航按钮选中态（因为 configure 覆盖了 fg_color 元组）
        current = self._current_nav
        self._current_nav = None
        if current:
            self._select_nav(current)
        # 重新应用当前状态胶囊
        self._reapply_status_pill()

    # ---- 引擎控制 ----

    def _start_engine(self):
        if self._engine and self._engine.is_alive():
            self._app_logger.warning("引擎已在运行")
            return

        self._engine = EngineThread(config_path=self._config_path)

        self._panels["dashboard"].engine_state = self._engine.state
        self._panels["history"].engine_state = self._engine.state

        if self._engine.start_engine():
            self._app_logger.info("引擎正在启动...")
            self._update_status_pill("starting")
        else:
            self._app_logger.error("引擎启动失败")
            self._update_status_pill("stopped")

    def _stop_engine(self):
        if self._engine and self._engine.is_alive():
            self._app_logger.info("正在停止引擎...")
            self._engine.stop_engine()
            self._update_status_pill("stopping")
            self._poll_engine_stop()
        else:
            self._app_logger.warning("引擎未运行")

    def _poll_engine_stop(self):
        if not self.winfo_exists():
            return
        if self._engine and self._engine.is_alive():
            self.after(200, self._poll_engine_stop)
        else:
            self._app_logger.info("引擎已停止")
            self._update_status_pill("stopped")

    def _reload_config(self):
        self._panels["config"].reload_config()
        self._app_logger.info("配置已重新加载")

    # ---- 状态胶囊 ----

    def _pill_configs(self):
        """返回各状态下的胶囊配色。使用 tuple 让其跟随主题。"""
        return {
            "running": {
                "pill": c("success_bg"),
                "light": c("success"),
                "text": c("success_text"),
                "label": "引擎运行中",
                "start": "disabled", "stop": "normal",
            },
            "starting": {
                "pill": c("warning_bg"),
                "light": c("warning"),
                "text": c("warning_text"),
                "label": "引擎启动中…",
                "start": "disabled", "stop": "disabled",
            },
            "stopping": {
                "pill": c("error_bg"),
                "light": ("#BC4C00", "#FF8C5A"),
                "text": c("error_text"),
                "label": "引擎停止中…",
                "start": "disabled", "stop": "disabled",
            },
            "stopped": {
                "pill": c("surface_2"),
                "light": c("text_low"),
                "text": c("text_med"),
                "label": "引擎未启动",
                "start": "normal", "stop": "disabled",
            },
        }

    def _update_status_pill(self, state: str):
        """state: 'stopped' | 'starting' | 'running' | 'stopping'"""
        self._pill_state = state  # 记忆当前态用于主题切换后重刷
        cfg = self._pill_configs().get(state, self._pill_configs()["stopped"])
        self._status_pill.configure(fg_color=cfg["pill"])
        self._status_light.configure(text_color=cfg["light"])
        self._status_text.configure(text=cfg["label"], text_color=cfg["text"])
        self._start_btn.configure(state=cfg["start"])
        self._stop_btn.configure(state=cfg["stop"])

    def _reapply_status_pill(self):
        self._update_status_pill(getattr(self, "_pill_state", "stopped"))

    # ---- 定期刷新 ----

    def _schedule_refresh(self):
        if not self.winfo_exists():
            return
        try:
            self._refresh_all()
        except Exception as e:
            self._app_logger.warning(f"刷新面板异常: {e}")
        self.after(self._refresh_interval, self._schedule_refresh)

    def _refresh_all(self):
        if self._engine and self._engine.state:
            snap = self._engine.state.snapshot()
            if snap.get("starting"):
                self._update_status_pill("starting")
            elif snap.get("running"):
                self._update_status_pill("running")
            else:
                self._update_status_pill("stopped")
        else:
            self._update_status_pill("stopped")

        # 仅刷新当前可见面板
        current = self._current_nav
        if current == "dashboard":
            self._panels["dashboard"].refresh()
        elif current == "history":
            self._panels["history"].refresh()
        elif current == "logs":
            self._panels["logs"].refresh()

        self._refresh_counter += 1
        if self._refresh_counter >= 30:
            self._refresh_counter = 0
            if current == "shots":
                self._panels["shots"].refresh()

    # ---- 关闭 ----

    def _on_close(self):
        if self._engine and self._engine.is_alive():
            self._app_logger.info("正在停止引擎...")
            self._engine.stop_engine()
        # 清理日志订阅
        for panel in self._panels.values():
            if hasattr(panel, "cleanup"):
                panel.cleanup()
        self.destroy()


def run_gui():
    """启动 GUI 应用程序。"""
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    app = WeChatAutoGuiApp()
    app.mainloop()


if __name__ == "__main__":
    run_gui()

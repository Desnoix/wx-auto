"""
仪表盘面板 — 显示引擎运行状态的核心信息。

布局：
  ┌─────────────────────────────────────────┐
  │  [● 运行中]    [启动] [停止]  [配置重载]│
  ├────────────────┬────────────────────────┤
  │  状态机状态     │  当前联系人：张三      │
  │  ┌──────────┐  │  队列中：3             │
  │  │ DETECT   │  │  已回复：42            │
  │  │ _UNREAD   │  │  错误：2              │
  │  └──────────┘  │  运行时间：01:23:45    │
  ├────────────────┴────────────────────────┤
  │  WeChat窗口：HWND=12345 1200x800 √      │
  │  日志路径：logs/wechat-auto.log         │
  │  最后错误: -                            │
  └─────────────────────────────────────────┘
"""

import datetime
import tkinter as tk
from typing import Optional

import customtkinter as ctk

from ..engine_thread import EngineState

# 状态对应颜色映射
STATE_COLORS: dict[str, str] = {
    "IDLE": "#888888",
    "MONITOR": "#4A90D9",
    "DETECT_UNREAD": "#F5A623",
    "OPEN_CHAT": "#7ED321",
    "READ_MESSAGE": "#50E3C2",
    "GENERATE_REPLY": "#B8E986",
    "SEND": "#4A90D9",
    "VERIFY": "#F8E71C",
    "COMPLETE": "#7ED321",
    "ERROR": "#D0021B",
}

STATE_DESCRIPTIONS: dict[str, str] = {
    "IDLE": "等待中 — 检查微信窗口",
    "MONITOR": "监控中 — 等待轮询间隔",
    "DETECT_UNREAD": "检测未读 — VL 识别 + OCR 定位",
    "OPEN_CHAT": "打开会话 — 点击联系人并验证标题",
    "READ_MESSAGE": "读取消息 — OCR 提取聊天内容",
    "GENERATE_REPLY": "生成回复 — LLM 生成回复文本",
    "SEND": "发送中 — 粘贴回复到输入框",
    "VERIFY": "验证中 — OCR 检查消息是否发出",
    "COMPLETE": "完成 — 记录结果，处理下一任务",
    "ERROR": "错误 — 查看日志了解详情",
}


class DashboardPanel(ctk.CTkFrame):
    """主仪表盘面板。"""

    def __init__(self, master, engine_state: EngineState,
                 on_start=None, on_stop=None, on_reload=None):
        super().__init__(master)
        self.engine_state = engine_state
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_reload = on_reload

        # 控制栏
        self._build_control_bar()
        # 状态显示区
        self._build_status_area()
        # 信息区
        self._build_info_area()

    # ---- 构建方法 ----

    def _build_control_bar(self):
        """构建顶部的控制按钮和状态指示器。"""
        bar = ctk.CTkFrame(self, height=60, corner_radius=8)
        bar.pack(fill="x", padx=12, pady=(12, 6))
        bar.pack_propagate(False)

        # 状态指示灯
        self._status_light = ctk.CTkLabel(
            bar, text="●", font=ctk.CTkFont(size=20), text_color="#888888", width=30
        )
        self._status_light.pack(side="left", padx=(15, 5))

        self._status_label = ctk.CTkLabel(
            bar, text="引擎未启动", font=ctk.CTkFont(size=14, weight="bold")
        )
        self._status_label.pack(side="left", padx=5)

        # 弹性空间
        ctk.CTkLabel(bar, text="").pack(side="left", fill="x", expand=True)

        # 控制按钮
        self._start_btn = ctk.CTkButton(
            bar, text="▶ 启动引擎", width=110, height=32,
            fg_color="#2E7D32", hover_color="#1B5E20",
            command=self._on_start_click,
        )
        self._start_btn.pack(side="right", padx=(5, 15))

        self._stop_btn = ctk.CTkButton(
            bar, text="■ 停止引擎", width=110, height=32,
            fg_color="#C62828", hover_color="#B71C1C",
            state="disabled", command=self._on_stop_click,
        )
        self._stop_btn.pack(side="right", padx=5)

        self._reload_btn = ctk.CTkButton(
            bar, text="⟳ 重载配置", width=100, height=32,
            fg_color="#455A64", hover_color="#37474F",
            command=self._on_reload_click,
        )
        self._reload_btn.pack(side="right", padx=5)

    def _build_status_area(self):
        """构建中间的状态卡片区域。"""
        main_area = ctk.CTkFrame(self)
        main_area.pack(fill="both", expand=True, padx=12, pady=6)

        main_area.grid_columnconfigure(0, weight=1)
        main_area.grid_columnconfigure(1, weight=1)
        main_area.grid_rowconfigure(0, weight=1)

        # 左侧：状态机状态卡片
        left_card = ctk.CTkFrame(main_area, corner_radius=10)
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=6)

        ctk.CTkLabel(
            left_card, text="状态机当前状态",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#90A4AE",
        ).pack(anchor="w", padx=16, pady=(16, 8))

        self._state_display = ctk.CTkLabel(
            left_card, text="IDLE",
            font=ctk.CTkFont(size=42, weight="bold"),
            text_color="#888888",
        )
        self._state_display.pack(padx=16, pady=(0, 4))

        self._state_desc = ctk.CTkLabel(
            left_card, text="等待中 — 检查微信窗口",
            font=ctk.CTkFont(size=12),
            text_color="#B0BEC5",
            wraplength=300,
        )
        self._state_desc.pack(padx=16, pady=(0, 16))

        # 进度条
        self._state_progress = ctk.CTkProgressBar(left_card, height=4)
        self._state_progress.pack(fill="x", padx=16, pady=(0, 16))
        self._state_progress.set(0)

        # 右侧：关键指标
        right_card = ctk.CTkFrame(main_area, corner_radius=10)
        right_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=6)

        ctk.CTkLabel(
            right_card, text="运行时指标",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#90A4AE",
        ).pack(anchor="w", padx=16, pady=(16, 12))

        self._build_metric_row(right_card, "当前联系人", "current_contact", "—")
        self._build_metric_row(right_card, "队列中待处理", "queue_size", "0")
        self._build_metric_row(right_card, "累计回复", "total_replies", "0")
        self._build_metric_row(right_card, "累计错误", "total_errors", "0")
        self._build_metric_row(right_card, "运行时间", "uptime", "00:00:00")

    def _build_metric_row(self, parent, label: str, key: str, default: str):
        """在右侧卡片中构建一行指标。"""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=4)

        ctk.CTkLabel(
            row, text=label,
            font=ctk.CTkFont(size=12), text_color="#B0BEC5",
        ).pack(side="left")

        value_label = ctk.CTkLabel(
            row, text=default,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#FFFFFF",
        )
        value_label.pack(side="right")

        setattr(self, f"_metric_{key}", value_label)

    def _build_info_area(self):
        """构建底部信息栏。"""
        info_bar = ctk.CTkFrame(self, height=80, corner_radius=8)
        info_bar.pack(fill="x", padx=12, pady=(6, 12))
        info_bar.pack_propagate(False)

        # WeChat 窗口状态
        self._wechat_status = ctk.CTkLabel(
            info_bar, text="微信窗口：未检测", anchor="w",
            font=ctk.CTkFont(size=12),
        )
        self._wechat_status.pack(anchor="w", padx=16, pady=(8, 2))

        # 最后错误
        self._error_status = ctk.CTkLabel(
            info_bar, text="最后错误：—", anchor="w",
            font=ctk.CTkFont(size=12), text_color="#EF9A9A",
        )
        self._error_status.pack(anchor="w", padx=16, pady=2)

    # ---- 按钮回调 ----

    def _on_start_click(self):
        if self._on_start:
            self._on_start()

    def _on_stop_click(self):
        if self._on_stop:
            self._on_stop()

    def _on_reload_click(self):
        if self._on_reload:
            self._on_reload()

    # ---- 控制按钮状态 ----

    def set_controls_running(self, running: bool):
        """根据运行状态切换按钮可用性。"""
        if running:
            self._start_btn.configure(state="disabled")
            self._stop_btn.configure(state="normal")
            self._status_label.configure(text="引擎运行中")
            self._status_light.configure(text_color="#4CAF50")
        else:
            self._start_btn.configure(state="normal")
            self._stop_btn.configure(state="disabled")
            self._status_label.configure(text="引擎已停止")
            self._status_light.configure(text_color="#888888")

    def set_controls_starting(self):
        """启动中状态（禁用按钮，显示黄灯）。"""
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="disabled")
        self._status_label.configure(text="引擎启动中...")
        self._status_light.configure(text_color="#FFA726")

    def set_controls_stopping(self):
        """停止中状态（禁用按钮，显示橙灯）。"""
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="disabled")
        self._status_label.configure(text="引擎停止中...")
        self._status_light.configure(text_color="#FF7043")

    # ---- 刷新方法（由 App 定期调用） ----

    def refresh(self):
        """刷新面板数据。"""
        if self.engine_state is None:
            self.set_controls_running(False)
            self._state_display.configure(text="IDLE")
            self._state_progress.set(0)
            return
        snap = self.engine_state.snapshot()

        # 检查"启动中"状态
        starting = snap.get("starting", False)
        running = snap.get("running", False)
        if starting:
            self.set_controls_starting()
        else:
            self.set_controls_running(running)

        # 状态机状态（引擎停止时重置为 IDLE）
        if not running and not starting:
            sm_state = "IDLE"
        else:
            sm_state = snap.get("state_machine_state", "IDLE")
        self._state_display.configure(text=sm_state)
        self._state_display.configure(
            text_color=STATE_COLORS.get(sm_state, "#FFFFFF")
        )
        self._state_desc.configure(
            text=STATE_DESCRIPTIONS.get(sm_state, "")
        )

        # 状态进度 — 正常工作流（排除 ERROR）
        normal_states = [
            "IDLE", "MONITOR", "DETECT_UNREAD", "OPEN_CHAT",
            "READ_MESSAGE", "GENERATE_REPLY", "SEND", "VERIFY",
            "COMPLETE",
        ]
        if sm_state == "ERROR" or not running:
            self._state_progress.set(0)  # ERROR 或停止时显示 0%
        elif sm_state in normal_states:
            progress = (normal_states.index(sm_state) + 1) / len(normal_states)
            self._state_progress.set(progress)

        # 指标
        self._update_metric(
            "current_contact",
            snap.get("current_contact", "—") or "—",
        )
        self._update_metric("queue_size", str(snap.get("queue_size", 0)))
        self._update_metric("total_replies", str(snap.get("total_replies", 0)))
        self._update_metric("total_errors", str(snap.get("total_errors", 0)))

        # 时间
        uptime_sec = snap.get("uptime_seconds", 0.0)
        self._update_metric("uptime", self._format_uptime(uptime_sec))

        # 微信状态
        wechat_found = snap.get("wechat_found", False)
        window_title = snap.get("window_title", "")
        if wechat_found:
            self._wechat_status.configure(
                text=f"微信窗口：✓ {window_title}",
                text_color="#A5D6A7",
            )
        else:
            self._wechat_status.configure(
                text="微信窗口：✗ 未找到",
                text_color="#EF9A9A",
            )

        # 最后错误
        last_error = snap.get("last_error", "")
        if last_error:
            self._error_status.configure(text=f"最后错误：{last_error}")

    def _update_metric(self, key: str, value: str):
        label = getattr(self, f"_metric_{key}", None)
        if label:
            label.configure(text=value)

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        """将秒数格式化为 HH:MM:SS。"""
        if seconds <= 0:
            return "00:00:00"
        td = datetime.timedelta(seconds=int(seconds))
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
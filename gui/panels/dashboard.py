"""
仪表盘面板 — 引擎运行状态的现代化可视化 + 首页实时日志流。

布局：
  ┌───────────────────────────────────────────────┐
  │ [5 指标卡片]                                    │
  ├────────────────────────┬──────────────────────┤
  │ 状态机流水线           │ 微信窗口 / 最后错误    │
  ├────────────────────────┴──────────────────────┤
  │ 实时日志流（最近 N 条，紧凑视图）              │
  └───────────────────────────────────────────────┘
"""

import datetime
import tkinter as tk
from typing import Optional

import customtkinter as ctk

# 兼容脚本 / package 两种导入方式
try:
    from ..engine_thread import EngineState
    from ..log_handler import GUIQueueHandler, GUILogRecord
    from ..theme import c, resolve, on_theme_change, LEVEL_STYLE, level_color
except ImportError:  # pragma: no cover
    from gui.engine_thread import EngineState
    from gui.log_handler import GUIQueueHandler, GUILogRecord
    from gui.theme import c, resolve, on_theme_change, LEVEL_STYLE, level_color


# 状态机 9 个正常状态 + 短名
PIPELINE_STATES: list[tuple[str, str]] = [
    ("IDLE",           "IDLE"),
    ("MONITOR",        "监控"),
    ("DETECT_UNREAD",  "检测"),
    ("OPEN_CHAT",      "打开"),
    ("READ_MESSAGE",   "读取"),
    ("GENERATE_REPLY", "生成"),
    ("SEND",           "发送"),
    ("VERIFY",         "验证"),
    ("COMPLETE",       "完成"),
]

STATE_ACCENT_KEY: dict[str, str] = {
    "IDLE":           "text_med",
    "MONITOR":        "dot_blue",
    "DETECT_UNREAD":  "dot_orange",
    "OPEN_CHAT":      "dot_green",
    "READ_MESSAGE":   "dot_teal",
    "GENERATE_REPLY": "dot_purple",
    "SEND":           "accent",
    "VERIFY":         "dot_yellow",
    "COMPLETE":       "success",
    "ERROR":          "error",
}

STATE_DESCRIPTIONS: dict[str, str] = {
    "IDLE":           "等待中 — 检查微信窗口",
    "MONITOR":        "监控中 — 等待轮询间隔",
    "DETECT_UNREAD":  "检测未读 — VL 识别 + OCR 定位",
    "OPEN_CHAT":      "打开会话 — 点击联系人并验证标题",
    "READ_MESSAGE":   "读取消息 — OCR 提取聊天内容",
    "GENERATE_REPLY": "生成回复 — LLM 生成回复文本",
    "SEND":           "发送中 — 粘贴回复到输入框",
    "VERIFY":         "验证中 — OCR 检查消息是否发出",
    "COMPLETE":       "完成 — 记录结果，处理下一任务",
    "ERROR":          "错误 — 查看日志了解详情",
}


def _has_font(name: str) -> bool:
    try:
        from tkinter import font as tkfont
        return name in tkfont.families()
    except Exception:
        return False


class DashboardPanel(ctk.CTkFrame):
    """主仪表盘面板 —— 信息展示 + 首页实时日志流。"""

    MINI_LOG_MAX = 200  # 首页日志最多保留行数

    def __init__(self, master, engine_state: Optional[EngineState] = None,
                 log_handler: Optional[GUIQueueHandler] = None, **_ignored):
        super().__init__(master, fg_color=c("bg"), corner_radius=0)
        self.engine_state = engine_state
        self._log_handler = log_handler
        self._log_sub = log_handler.subscribe() if log_handler else None
        self._mini_line_count = 0

        # 记录指标标签，便于 refresh() 更新
        self._metric_labels: dict[str, ctk.CTkLabel] = {}
        self._state_pills: dict[str, dict] = {}
        self._last_sm_state: Optional[str] = None
        self._last_running: Optional[bool] = None

        # 使用 grid 布局，让底部日志流可扩展
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)  # 底部日志区

        self._build_metric_row()
        self._build_state_and_info_row()
        self._build_mini_log()

        # 注册主题变更
        on_theme_change(self._apply_theme_to_text)

    # ---- 构建 ----

    def _build_metric_row(self):
        """一行指标卡片。"""
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        for i in range(5):
            row.grid_columnconfigure(i, weight=1, uniform="metric")

        cards = [
            ("current_contact", "当前联系人", "—",       "accent"),
            ("queue_size",      "队列",       "0",       "dot_blue"),
            ("total_replies",   "累计回复",   "0",       "success"),
            ("total_errors",    "累计错误",   "0",       "error"),
            ("uptime",          "运行时间",   "00:00:00", "warning"),
        ]

        for i, (key, label, default, accent_key) in enumerate(cards):
            self._build_metric_card(row, i, key, label, default, accent_key)

    def _build_metric_card(self, parent, col: int, key: str,
                           label: str, default: str, accent_key: str):
        card = ctk.CTkFrame(parent, fg_color=c("surface"), corner_radius=12)
        card.grid(row=0, column=col, sticky="nsew", padx=6)

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 2))
        ctk.CTkLabel(
            head, text="■", font=ctk.CTkFont(size=10),
            text_color=c(accent_key),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(
            head, text=label, font=ctk.CTkFont(size=11),
            text_color=c("text_med"), anchor="w",
        ).pack(side="left")

        value = ctk.CTkLabel(
            card, text=default,
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=c("text_hi"), anchor="w",
        )
        value.pack(anchor="w", padx=16, pady=(2, 14))

        self._metric_labels[key] = value

    def _build_state_and_info_row(self):
        """中间一行：左=状态机卡片，右=微信/错误信息竖排。"""
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", pady=6)
        row.grid_columnconfigure(0, weight=3)
        row.grid_columnconfigure(1, weight=2)

        # 左：状态机卡片
        state_card = self._build_state_card(row)
        state_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        # 右：信息卡片列
        info_col = ctk.CTkFrame(row, fg_color="transparent")
        info_col.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        info_col.grid_columnconfigure(0, weight=1)
        info_col.grid_rowconfigure(0, weight=1)
        info_col.grid_rowconfigure(1, weight=1)

        self._build_wechat_card(info_col)
        self._build_error_card(info_col)

    def _build_state_card(self, parent) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color=c("surface"), corner_radius=12)

        # 头部
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(16, 6))

        ctk.CTkLabel(
            head, text="状态机",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=c("text_low"), anchor="w",
        ).pack(anchor="w")

        state_row = ctk.CTkFrame(head, fg_color="transparent")
        state_row.pack(anchor="w", pady=(2, 0))

        self._state_dot = ctk.CTkLabel(
            state_row, text="●", font=ctk.CTkFont(size=15),
            text_color=c("text_low"),
        )
        self._state_dot.pack(side="left", padx=(0, 8))

        self._state_display = ctk.CTkLabel(
            state_row, text="IDLE",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=c("text_hi"),
        )
        self._state_display.pack(side="left")

        # 描述
        self._state_desc = ctk.CTkLabel(
            card, text=STATE_DESCRIPTIONS["IDLE"],
            font=ctk.CTkFont(size=11), text_color=c("text_med"),
            anchor="w",
        )
        self._state_desc.pack(anchor="w", padx=18, pady=(0, 10))

        # 进度条
        self._state_progress = ctk.CTkProgressBar(
            card, height=4, progress_color=c("accent"),
            fg_color=c("surface_2"),
        )
        self._state_progress.pack(fill="x", padx=18, pady=(0, 12))
        self._state_progress.set(0)

        # 分隔线
        ctk.CTkFrame(card, height=1, fg_color=c("border")).pack(
            fill="x", padx=18,
        )

        # 流水线
        pipe = ctk.CTkFrame(card, fg_color="transparent")
        pipe.pack(fill="x", padx=18, pady=(12, 16))

        for i, (state, short) in enumerate(PIPELINE_STATES):
            if i > 0:
                ctk.CTkLabel(
                    pipe, text="›",
                    font=ctk.CTkFont(size=13),
                    text_color=c("text_low"),
                ).pack(side="left", padx=2)

            pill = ctk.CTkFrame(
                pipe, fg_color=c("surface_2"), corner_radius=999,
                height=26,
            )
            pill.pack(side="left", padx=1)
            pill.pack_propagate(False)

            dot = ctk.CTkLabel(
                pill, text="●", font=ctk.CTkFont(size=8),
                text_color=c("text_low"),
            )
            dot.pack(side="left", padx=(8, 3))

            lbl = ctk.CTkLabel(
                pill, text=short,
                font=ctk.CTkFont(size=10),
                text_color=c("text_med"),
            )
            lbl.pack(side="left", padx=(0, 10))

            self._state_pills[state] = {
                "frame": pill, "label": lbl, "dot": dot,
            }

        return card

    def _build_wechat_card(self, parent):
        wc = ctk.CTkFrame(parent, fg_color=c("surface"), corner_radius=12)
        wc.grid(row=0, column=0, sticky="nsew", pady=(0, 6))

        ctk.CTkLabel(
            wc, text="微信窗口",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=c("text_low"), anchor="w",
        ).pack(anchor="w", padx=16, pady=(14, 4))

        self._wechat_icon = ctk.CTkLabel(
            wc, text="✗ 未找到",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=c("error"), anchor="w",
        )
        self._wechat_icon.pack(anchor="w", padx=16)

        self._wechat_detail = ctk.CTkLabel(
            wc, text="等待引擎启动后检测",
            font=ctk.CTkFont(size=10), text_color=c("text_med"),
            anchor="w",
        )
        self._wechat_detail.pack(anchor="w", padx=16, pady=(2, 14))

    def _build_error_card(self, parent):
        ec = ctk.CTkFrame(parent, fg_color=c("surface"), corner_radius=12)
        ec.grid(row=1, column=0, sticky="nsew", pady=(6, 0))

        ctk.CTkLabel(
            ec, text="最后错误",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=c("text_low"), anchor="w",
        ).pack(anchor="w", padx=16, pady=(14, 4))

        self._error_display = ctk.CTkLabel(
            ec, text="—",
            font=ctk.CTkFont(size=11),
            text_color=c("text_med"), anchor="w",
            wraplength=380, justify="left",
        )
        self._error_display.pack(anchor="w", padx=16, pady=(0, 14))

    def _build_mini_log(self):
        """底部实时日志流。"""
        card = ctk.CTkFrame(self, fg_color=c("surface"), corner_radius=12)
        card.grid(row=2, column=0, sticky="nsew", pady=(12, 0))

        # 头部
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            head, text="● 实时日志",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=c("accent"),
        ).pack(side="left")

        ctk.CTkLabel(
            head, text=f"（首页只显示，完整日志请切换到 “日志” 页）",
            font=ctk.CTkFont(size=10), text_color=c("text_low"),
        ).pack(side="left", padx=(8, 0))

        # 清空按钮
        self._mini_clear_btn = ctk.CTkButton(
            head, text="清空", width=54, height=24, corner_radius=6,
            fg_color="transparent", border_width=1,
            border_color=c("border"),
            text_color=c("text_med"), hover_color=c("surface_2"),
            font=ctk.CTkFont(size=10),
            command=self._clear_mini_log,
        )
        self._mini_clear_btn.pack(side="right")

        # 日志文本区
        inner = ctk.CTkFrame(card, corner_radius=8, fg_color=c("editor_bg"))
        inner.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        font_family = "JetBrains Mono" if _has_font("JetBrains Mono") else "Consolas"
        self._mini_text = tk.Text(
            inner,
            bg=resolve("editor_bg"),
            fg=resolve("editor_text"),
            font=(font_family, 10),
            wrap="none",
            state="disabled",
            padx=12, pady=8,
            relief="flat", borderwidth=0, highlightthickness=0,
            spacing1=1, spacing3=1,
            selectbackground=resolve("accent"),
            selectforeground=resolve("accent_text"),
        )

        v = ctk.CTkScrollbar(
            inner, command=self._mini_text.yview,
            fg_color="transparent", button_color=c("border"),
            button_hover_color=c("text_low"),
        )
        self._mini_text.configure(yscrollcommand=v.set)

        self._mini_text.grid(row=0, column=0, sticky="nsew")
        v.grid(row=0, column=1, sticky="ns")
        inner.grid_rowconfigure(0, weight=1)
        inner.grid_columnconfigure(0, weight=1)

        self._apply_theme_to_text()

    # ---- 主题应用（tk.Text 需要手动） ----

    def _apply_theme_to_text(self, _mode: Optional[str] = None):
        if not hasattr(self, "_mini_text"):
            return
        self._mini_text.configure(
            bg=resolve("editor_bg"),
            fg=resolve("editor_text"),
            selectbackground=resolve("accent"),
            selectforeground=resolve("accent_text"),
        )
        self._mini_text.tag_config("ts", foreground=resolve("text_low"))
        self._mini_text.tag_config("logger", foreground=resolve("text_med"))
        for level in LEVEL_STYLE:
            self._mini_text.tag_config(
                f"badge_{level}",
                foreground=level_color(level, "badge_fg"),
                background=level_color(level, "badge_bg"),
                font=("Consolas", 9, "bold"),
                lmargin1=2, lmargin2=2,
            )
            self._mini_text.tag_config(
                f"msg_{level}",
                foreground=level_color(level, "msg_fg"),
            )

    # ---- 刷新 ----

    def refresh(self):
        """由 App 定期调用。"""
        self._refresh_stats()
        self._pump_logs()

    def _refresh_stats(self):
        if self.engine_state is None:
            self._apply_state("IDLE", running=False)
            return

        snap = self.engine_state.snapshot()
        starting = snap.get("starting", False)
        running = snap.get("running", False)

        if not running and not starting:
            sm_state = "IDLE"
        else:
            sm_state = snap.get("state_machine_state", "IDLE")

        self._apply_state(sm_state, running=running)

        # 指标
        self._set_metric("current_contact",
                         snap.get("current_contact", "—") or "—")
        self._set_metric("queue_size", str(snap.get("queue_size", 0)))
        self._set_metric("total_replies", str(snap.get("total_replies", 0)))
        self._set_metric("total_errors", str(snap.get("total_errors", 0)))
        self._set_metric("uptime", self._format_uptime(
            snap.get("uptime_seconds", 0.0)))

        # 微信窗口
        if snap.get("wechat_found"):
            self._wechat_icon.configure(text="✓ 已连接", text_color=c("success"))
            self._wechat_detail.configure(
                text=snap.get("window_title", "") or "微信主窗口",
                text_color=c("text_med"),
            )
        else:
            self._wechat_icon.configure(text="✗ 未找到", text_color=c("error"))
            self._wechat_detail.configure(
                text="启动微信 4.x 并保持登录",
                text_color=c("text_med"),
            )

        # 最后错误
        last_error = snap.get("last_error", "")
        if last_error:
            self._error_display.configure(text=last_error, text_color=c("error_text"))
        else:
            self._error_display.configure(text="—", text_color=c("text_med"))

    def _apply_state(self, sm_state: str, running: bool):
        if sm_state == self._last_sm_state and running == self._last_running:
            return
        self._last_sm_state = sm_state
        self._last_running = running

        accent = c(STATE_ACCENT_KEY.get(sm_state, "text_hi"))
        self._state_dot.configure(text_color=accent)
        self._state_display.configure(text=sm_state, text_color=accent)
        self._state_desc.configure(text=STATE_DESCRIPTIONS.get(sm_state, ""))

        normal = [s for s, _ in PIPELINE_STATES]
        if sm_state == "ERROR" or not running:
            self._state_progress.set(0)
        elif sm_state in normal:
            self._state_progress.set((normal.index(sm_state) + 1) / len(normal))
        self._state_progress.configure(progress_color=accent)

        current_idx = normal.index(sm_state) if sm_state in normal else -1
        for i, (state, _) in enumerate(PIPELINE_STATES):
            info = self._state_pills[state]
            if i == current_idx:
                info["frame"].configure(fg_color=accent)
                info["dot"].configure(text_color=c("accent_text"))
                info["label"].configure(
                    text_color=c("accent_text"),
                    font=ctk.CTkFont(size=10, weight="bold"),
                )
            elif i < current_idx:
                info["frame"].configure(fg_color=c("surface_2"))
                info["dot"].configure(text_color=c("success"))
                info["label"].configure(
                    text_color=c("text_hi"),
                    font=ctk.CTkFont(size=10),
                )
            else:
                info["frame"].configure(fg_color=c("surface_2"))
                info["dot"].configure(text_color=c("text_low"))
                info["label"].configure(
                    text_color=c("text_med"),
                    font=ctk.CTkFont(size=10),
                )

    def _set_metric(self, key: str, value: str):
        label = self._metric_labels.get(key)
        if label and label.cget("text") != value:
            label.configure(text=value)

    # ---- 首页日志流 ----

    def _pump_logs(self):
        """从订阅队列抽取日志并追加显示。"""
        if self._log_sub is None:
            return
        # 插入前记录用户是否已在底部，避免新内容拉低 yview 后误判
        was_at_bottom = self._mini_text.yview()[1] >= 0.999
        added = 0
        self._mini_text.configure(state="normal")
        while not self._log_sub.empty() and added < 200:
            try:
                rec = self._log_sub.get_nowait()
            except Exception:
                break
            self._insert_record(rec)
            self._mini_line_count += 1
            added += 1
        # 批量修剪
        overflow = self._mini_line_count - self.MINI_LOG_MAX
        if overflow > 0:
            self._mini_text.delete("1.0", f"{overflow + 1}.0")
            self._mini_line_count -= overflow
        if added > 0 and was_at_bottom:
            self._mini_text.see("end")
        self._mini_text.configure(state="disabled")

    def _insert_record(self, rec: GUILogRecord):
        style = LEVEL_STYLE.get(rec.levelname, LEVEL_STYLE["INFO"])
        level = rec.levelname if rec.levelname in LEVEL_STYLE else "INFO"
        # 时间戳
        self._mini_text.insert("end", rec.timestamp + "  ", "ts")
        # 徽章
        self._mini_text.insert("end", f" {style['short']} ", f"badge_{level}")
        # 来源
        self._mini_text.insert("end", "  " + rec.name + "  ", "logger")
        # 正文
        self._mini_text.insert("end", rec.message + "\n", f"msg_{level}")

    def _clear_mini_log(self):
        self._mini_text.configure(state="normal")
        self._mini_text.delete("1.0", "end")
        self._mini_text.configure(state="disabled")
        self._mini_line_count = 0

    def cleanup(self):
        """释放资源：取消日志订阅。"""
        if self._log_handler and self._log_sub:
            self._log_handler.unsubscribe(self._log_sub)
            self._log_sub = None

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        if seconds <= 0:
            return "00:00:00"
        td = datetime.timedelta(seconds=int(seconds))
        total = int(td.total_seconds())
        h = total // 3600
        m = (total % 3600) // 60
        s = total % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

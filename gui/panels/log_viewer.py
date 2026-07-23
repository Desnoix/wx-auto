"""
日志查看器面板 — 实时显示引擎日志。

特性：
  - 分段渲染：时间戳 / 级别徽章 / 来源 / 正文
  - 级别快速过滤 + 关键字过滤（高亮匹配）
  - 自动滚动开关 · 自动换行开关
  - 复制可见 · 导出全部 · 清空
  - 支持 Light / Dark 主题切换
"""

import tkinter as tk
from tkinter import filedialog
from typing import Optional

import customtkinter as ctk

try:
    from ..log_handler import GUIQueueHandler, GUILogRecord
    from ..theme import c, resolve, on_theme_change, LEVEL_STYLE, level_color
except ImportError:  # pragma: no cover
    from gui.log_handler import GUIQueueHandler, GUILogRecord
    from gui.theme import c, resolve, on_theme_change, LEVEL_STYLE, level_color


LEVEL_ORDER = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

FILTER_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("全部",   ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")),
    ("信息+",  ("INFO", "WARNING", "ERROR", "CRITICAL")),
    ("警告+",  ("WARNING", "ERROR", "CRITICAL")),
    ("仅错误", ("ERROR", "CRITICAL")),
]


def _has_font(name: str) -> bool:
    try:
        from tkinter import font as tkfont
        return name in tkfont.families()
    except Exception:
        return False


class LogViewerPanel(ctk.CTkFrame):
    """实时日志查看器。"""

    MAX_LINES = 3000

    def __init__(self, master, log_handler: GUIQueueHandler):
        super().__init__(master, fg_color=c("bg"), corner_radius=0)
        self._handler = log_handler
        self._sub = log_handler.subscribe()
        self._auto_scroll = True
        self._wrap = False
        self._search_text = ""
        self._enabled_levels: set[str] = set(LEVEL_ORDER)
        self._line_count = 0
        self._filter_group_var = tk.StringVar(value="全部")

        # 缓冲用于过滤切换时重建
        self._buffer: list[GUILogRecord] = []
        self._buffer_max = self.MAX_LINES
        self._search_debounce_id = None

        self._build_toolbar()
        self._build_log_view()

        # 应用初始主题到 tk.Text，并注册主题切换钩子
        self._apply_theme_to_text()
        on_theme_change(self._apply_theme_to_text)

    # ---- 构建 ----

    def _build_toolbar(self):
        """两行工具栏：上=级别过滤+统计，下=搜索+开关+操作。"""
        # 上行
        top = ctk.CTkFrame(self, height=44, corner_radius=10, fg_color=c("surface"))
        top.pack(fill="x", pady=(0, 8))
        top.pack_propagate(False)

        ctk.CTkLabel(
            top, text="级别", font=ctk.CTkFont(size=11, weight="bold"),
            text_color=c("text_low"),
        ).pack(side="left", padx=(16, 10))

        self._level_seg = ctk.CTkSegmentedButton(
            top, values=[g[0] for g in FILTER_GROUPS],
            variable=self._filter_group_var,
            command=self._on_filter_group_changed,
            height=28,
            selected_color=c("accent"),
            selected_hover_color=c("accent_hov"),
            unselected_color=c("surface_2"),
            unselected_hover_color=c("border_strong"),
            text_color=c("text_hi"),
        )
        self._level_seg.pack(side="left", padx=2)

        # 右：计数 + 丢弃提示
        self._log_count_label = ctk.CTkLabel(
            top, text="0 条", font=ctk.CTkFont(size=12),
            text_color=c("text_med"),
        )
        self._log_count_label.pack(side="right", padx=16)

        self._drop_label = ctk.CTkLabel(
            top, text="", font=ctk.CTkFont(size=11),
            text_color=c("warning"),
        )
        self._drop_label.pack(side="right", padx=4)

        # 下行
        bar = ctk.CTkFrame(self, height=44, corner_radius=10, fg_color=c("surface"))
        bar.pack(fill="x", pady=(0, 8))
        bar.pack_propagate(False)

        ctk.CTkLabel(
            bar, text="⌕", font=ctk.CTkFont(size=16),
            text_color=c("text_low"),
        ).pack(side="left", padx=(16, 4))

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *a: self._on_search_changed())
        self._search_entry = ctk.CTkEntry(
            bar, width=260, height=30,
            placeholder_text="过滤关键字（大小写不敏感）",
            textvariable=self._search_var,
            fg_color=c("surface_2"),
            border_color=c("border"),
            border_width=1,
            text_color=c("text_hi"),
        )
        self._search_entry.pack(side="left", padx=6)

        ctk.CTkLabel(bar, text="").pack(side="left", fill="x", expand=True)

        # 自动滚动
        self._autoscroll_switch = ctk.CTkSwitch(
            bar, text="自动滚动", command=self._toggle_autoscroll,
            onvalue=1, offvalue=0,
            progress_color=c("accent"),
            button_color=c("text_hi"),
            text_color=c("text_med"),
            font=ctk.CTkFont(size=11),
        )
        self._autoscroll_switch.select()
        self._autoscroll_switch.pack(side="left", padx=8)

        # 换行
        self._wrap_switch = ctk.CTkSwitch(
            bar, text="换行", command=self._toggle_wrap,
            onvalue=1, offvalue=0,
            progress_color=c("accent"),
            button_color=c("text_hi"),
            text_color=c("text_med"),
            font=ctk.CTkFont(size=11),
        )
        self._wrap_switch.pack(side="left", padx=8)

        # 操作
        self._copy_btn = ctk.CTkButton(
            bar, text="复制", width=64, height=28, corner_radius=6,
            fg_color=c("surface_2"), hover_color=c("border_strong"),
            text_color=c("text_hi"), font=ctk.CTkFont(size=11),
            command=self._copy_visible,
        )
        self._copy_btn.pack(side="right", padx=(4, 16))

        self._export_btn = ctk.CTkButton(
            bar, text="导出", width=64, height=28, corner_radius=6,
            fg_color=c("surface_2"), hover_color=c("border_strong"),
            text_color=c("text_hi"), font=ctk.CTkFont(size=11),
            command=self._export_log,
        )
        self._export_btn.pack(side="right", padx=4)

        self._clear_btn = ctk.CTkButton(
            bar, text="清空", width=64, height=28, corner_radius=6,
            fg_color=c("error_bg"), hover_color=c("error_hov"),
            text_color=c("error_text"), font=ctk.CTkFont(size=11),
            command=self._clear_log,
        )
        self._clear_btn.pack(side="right", padx=4)

    def _build_log_view(self):
        """构建日志文本显示区域。"""
        container = ctk.CTkFrame(self, corner_radius=10, fg_color=c("surface"))
        container.pack(fill="both", expand=True)

        inner = ctk.CTkFrame(container, corner_radius=8, fg_color=c("editor_bg"))
        inner.pack(fill="both", expand=True, padx=10, pady=10)

        font_family = "JetBrains Mono" if _has_font("JetBrains Mono") else "Consolas"

        self._text = tk.Text(
            inner,
            font=(font_family, 10) if font_family == "JetBrains Mono" else ("Consolas", 11),
            wrap="none",
            state="disabled",
            padx=14,
            pady=10,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            spacing1=2,
            spacing3=2,
        )

        v = ctk.CTkScrollbar(
            inner, command=self._text.yview,
            fg_color="transparent", button_color=c("border"),
            button_hover_color=c("text_low"),
        )
        h = ctk.CTkScrollbar(
            inner, orientation="horizontal", command=self._text.xview,
            fg_color="transparent", button_color=c("border"),
            button_hover_color=c("text_low"),
        )
        self._text.configure(yscrollcommand=v.set, xscrollcommand=h.set)

        self._text.grid(row=0, column=0, sticky="nsew")
        v.grid(row=0, column=1, sticky="ns")
        h.grid(row=1, column=0, sticky="ew")
        inner.grid_rowconfigure(0, weight=1)
        inner.grid_columnconfigure(0, weight=1)

    # ---- 主题应用（tk.Text 需要手动） ----

    def _apply_theme_to_text(self, _mode: Optional[str] = None):
        if not hasattr(self, "_text"):
            return
        self._text.configure(
            bg=resolve("editor_bg"),
            fg=resolve("editor_text"),
            insertbackground=resolve("editor_text"),
            selectbackground=resolve("accent"),
            selectforeground=resolve("accent_text"),
        )
        self._text.tag_config("ts", foreground=resolve("text_low"))
        self._text.tag_config("logger", foreground=resolve("text_med"))
        self._text.tag_config("sep", foreground=resolve("border"))
        for level in LEVEL_STYLE:
            self._text.tag_config(
                f"badge_{level}",
                foreground=level_color(level, "badge_fg"),
                background=level_color(level, "badge_bg"),
                font=("Consolas", 9, "bold"),
                lmargin1=2, lmargin2=2,
            )
            self._text.tag_config(
                f"msg_{level}",
                foreground=level_color(level, "msg_fg"),
            )
        self._text.tag_config(
            "highlight",
            background=resolve("hl_bg"),
            foreground=resolve("hl_fg"),
        )

    # ---- 事件 ----

    def _on_filter_group_changed(self, value: str):
        for label, levels in FILTER_GROUPS:
            if label == value:
                self._enabled_levels = set(levels)
                break
        self._rebuild_view()

    def _on_search_changed(self):
        if self._search_debounce_id is not None:
            self.after_cancel(self._search_debounce_id)
        self._search_debounce_id = self.after(300, self._apply_search)

    def _apply_search(self):
        self._search_debounce_id = None
        self._search_text = self._search_var.get().strip()
        self._rebuild_view()

    def _toggle_autoscroll(self):
        self._auto_scroll = bool(self._autoscroll_switch.get())
        if self._auto_scroll:
            self._text.see("end")

    def _toggle_wrap(self):
        self._wrap = bool(self._wrap_switch.get())
        self._text.configure(wrap="word" if self._wrap else "none")

    def _clear_log(self):
        self._buffer.clear()
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")
        self._line_count = 0
        self._log_count_label.configure(text="0 条")
        self._drop_label.configure(text="")

    def _copy_visible(self):
        content = self._text.get("1.0", "end-1c")
        if not content:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(content)
            self._flash_status(f"✓ 已复制 {self._line_count} 行")
        except Exception as e:
            self._flash_status(f"✗ 复制失败: {e}", error=True)

    def _export_log(self):
        if not self._buffer:
            self._flash_status("缓冲为空", error=True)
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".log",
            filetypes=[("Log 文件", "*.log"), ("文本文件", "*.txt"), ("全部", "*.*")],
            initialfile="wechat-auto-export.log",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                for rec in self._buffer:
                    f.write(rec.formatted + "\n")
            self._flash_status(f"✓ 已导出 {len(self._buffer)} 行")
        except Exception as e:
            self._flash_status(f"✗ 导出失败: {e}", error=True)

    def _flash_status(self, text: str, error: bool = False):
        self._drop_label.configure(
            text=text, text_color=c("error") if error else c("success"),
        )
        self.after(2500, lambda: self._drop_label.configure(
            text=self._current_drop_text(), text_color=c("warning"),
        ))

    def _current_drop_text(self) -> str:
        dc = self._handler.discard_count
        return f"⚠ 已丢弃 {dc} 条" if dc else ""

    # ---- 刷新 ----

    def refresh(self):
        """由 App 定期调用。"""
        records: list[GUILogRecord] = []
        while not self._sub.empty():
            try:
                records.append(self._sub.get_nowait())
            except Exception:
                break
        if not records:
            drop_text = self._current_drop_text()
            if drop_text and self._drop_label.cget("text") != drop_text:
                self._drop_label.configure(text=drop_text, text_color=c("warning"))
            return

        self._buffer.extend(records)
        if len(self._buffer) > self._buffer_max:
            del self._buffer[:-self._buffer_max]

        self._text.configure(state="normal")
        for rec in records:
            if not self._passes_filter(rec):
                continue
            self._insert_record(rec)
            self._line_count += 1

        overflow = self._line_count - self.MAX_LINES
        if overflow > 0:
            self._text.delete("1.0", f"{overflow + 1}.0")
            self._line_count -= overflow

        if self._auto_scroll:
            self._text.see("end")
        self._text.configure(state="disabled")

        self._update_stats()

    def _passes_filter(self, rec: GUILogRecord) -> bool:
        if rec.levelname not in self._enabled_levels:
            return False
        if self._search_text:
            needle = self._search_text.lower()
            hay = f"{rec.name} {rec.message}".lower()
            if needle not in hay:
                return False
        return True

    def _insert_record(self, rec: GUILogRecord):
        style = LEVEL_STYLE.get(rec.levelname, LEVEL_STYLE["INFO"])
        level = rec.levelname if rec.levelname in LEVEL_STYLE else "INFO"
        badge_tag = f"badge_{level}"
        msg_tag = f"msg_{level}"

        self._text.insert("end", rec.timestamp + "  ", "ts")
        self._text.insert("end", f" {style['short']} ", badge_tag)
        self._text.insert("end", "  " + rec.name + "  ", "logger")

        start_index = self._text.index("end-1c")
        self._text.insert("end", rec.message, msg_tag)
        end_index = self._text.index("end-1c")
        self._text.insert("end", "\n")

        if self._search_text:
            self._apply_highlight(start_index, end_index, self._search_text)

    def _apply_highlight(self, start: str, end: str, needle: str):
        try:
            idx = start
            while True:
                found = self._text.search(needle, idx, stopindex=end, nocase=1)
                if not found:
                    break
                end_of_match = f"{found}+{len(needle)}c"
                self._text.tag_add("highlight", found, end_of_match)
                idx = end_of_match
        except tk.TclError:
            pass

    def _rebuild_view(self):
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._line_count = 0
        for rec in self._buffer:
            if not self._passes_filter(rec):
                continue
            self._insert_record(rec)
            self._line_count += 1
            if self._line_count > self.MAX_LINES:
                self._text.delete("1.0", "2.0")
                self._line_count -= 1
        if self._auto_scroll:
            self._text.see("end")
        self._text.configure(state="disabled")
        self._update_stats()

    def _update_stats(self):
        total = len(self._buffer)
        if self._search_text or len(self._enabled_levels) < len(LEVEL_ORDER):
            self._log_count_label.configure(text=f"{self._line_count} / {total} 条")
        else:
            self._log_count_label.configure(text=f"{total} 条")

        drop_text = self._current_drop_text()
        if drop_text and self._drop_label.cget("text") != drop_text:
            self._drop_label.configure(text=drop_text, text_color=c("warning"))

    def cleanup(self):
        """释放资源：取消日志订阅。"""
        if self._handler and self._sub:
            self._handler.unsubscribe(self._sub)
            self._sub = None

"""
日志查看器面板 — 实时显示来自引擎线程的日志记录。

支持：
  - 颜色编码：ERROR(红)、WARNING(黄)、INFO(白)、DEBUG(灰)
  - 自动滚动/暂停
  - 搜索过滤
  - 清空
"""

import re
import tkinter as tk
from typing import Optional

import customtkinter as ctk

from ..log_handler import GUIQueueHandler

# 日志级别 -> 颜色映射
LEVEL_COLORS: dict[str, str] = {
    "CRITICAL": "#D50000",
    "ERROR": "#FF1744",
    "WARNING": "#FFD600",
    "INFO": "#E0E0E0",
    "DEBUG": "#616161",
}

LEVEL_TAGS: dict[str, str] = {
    "CRITICAL": "critical",
    "ERROR": "error",
    "WARNING": "warning",
    "INFO": "info",
    "DEBUG": "debug",
}


class LogViewerPanel(ctk.CTkFrame):
    """实时日志查看器。"""

    def __init__(self, master, log_handler: GUIQueueHandler):
        super().__init__(master)
        self._handler = log_handler
        self._auto_scroll = True
        self._filter_text = ""
        self._max_lines = 500
        self._line_count = 0

        self._build_toolbar()
        self._build_log_view()

    # ---- 构建 ----

    def _build_toolbar(self):
        """工具栏：搜索、暂停、清空、计数。"""
        toolbar = ctk.CTkFrame(self, height=40, corner_radius=6)
        toolbar.pack(fill="x", padx=8, pady=(8, 4))
        toolbar.pack_propagate(False)

        ctk.CTkLabel(toolbar, text="🔍", font=ctk.CTkFont(size=14)).pack(
            side="left", padx=(10, 4)
        )

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *a: self._on_search_changed())
        self._search_entry = ctk.CTkEntry(
            toolbar, width=200, height=28, placeholder_text="过滤日志...",
            textvariable=self._search_var,
        )
        self._search_entry.pack(side="left", padx=4)

        ctk.CTkLabel(toolbar, text="").pack(side="left", fill="x", expand=True)

        self._log_count_label = ctk.CTkLabel(
            toolbar, text="0 条", font=ctk.CTkFont(size=12), text_color="#90A4AE",
        )
        self._log_count_label.pack(side="right", padx=10)

        self._pause_btn = ctk.CTkButton(
            toolbar, text="⏸ 暂停", width=70, height=28,
            fg_color="#546E7A", hover_color="#455A64",
            command=self._toggle_pause,
        )
        self._pause_btn.pack(side="right", padx=4)

        self._clear_btn = ctk.CTkButton(
            toolbar, text="🗑 清空", width=70, height=28,
            fg_color="#546E7A", hover_color="#455A64",
            command=self._clear_log,
        )
        self._clear_btn.pack(side="right", padx=4)

    def _build_log_view(self):
        """构建日志文本显示区域。"""
        container = ctk.CTkFrame(self)
        container.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        # 使用 tkinter Text 实现颜色标签
        self._text = tk.Text(
            container,
            bg="#1E1E1E",
            fg="#E0E0E0",
            font=("Consolas", 11),
            wrap="none",
            state="disabled",
            padx=8,
            pady=8,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
        )

        # 滚轮
        v_scrollbar = ctk.CTkScrollbar(container, command=self._text.yview)
        h_scrollbar = ctk.CTkScrollbar(
            container, orientation="horizontal", command=self._text.xview
        )
        self._text.configure(
            yscrollcommand=v_scrollbar.set,
            xscrollcommand=h_scrollbar.set,
        )

        self._text.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        # 配置文本标签
        self._text.tag_config("critical", foreground="#D50000", font=("Consolas", 11, "bold"))
        self._text.tag_config("error", foreground="#FF1744")
        self._text.tag_config("warning", foreground="#FFD600")
        self._text.tag_config("info", foreground="#E0E0E0")
        self._text.tag_config("debug", foreground="#616161")
        self._text.tag_config("highlight", background="#3E2723")

        # 绑定滚轮到暂停
        self._text.bind("<Enter>", lambda e: setattr(self, '_auto_scroll', False))
        self._text.bind("<Leave>", lambda e: setattr(self, '_auto_scroll', True))
        self._text.bind("<Button-4>", lambda e: setattr(self, '_auto_scroll', False))
        self._text.bind("<Button-5>", lambda e: setattr(self, '_auto_scroll', False))

    # ---- 操作 ----

    def _toggle_pause(self):
        self._auto_scroll = not self._auto_scroll
        if self._auto_scroll:
            self._pause_btn.configure(text="⏸ 暂停")
        else:
            self._pause_btn.configure(text="▶ 滚动")

    def _clear_log(self):
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")
        self._line_count = 0
        self._log_count_label.configure(text="0 条")

    def _on_search_changed(self):
        self._filter_text = self._search_var.get()
        # 搜索变更时清除并重建已有内容（应用过滤到已有日志）
        self._apply_filter_to_existing()

    def _apply_filter_to_existing(self):
        """重新过滤文本视图中已有的内容。"""
        self._text.configure(state="normal")
        # 收集所有行
        all_lines = self._text.get("1.0", "end-1c").split("\n") if self._text.get("1.0", "end-1c") else []
        old_count = len(all_lines)
        # 清除并重建
        self._text.delete("1.0", "end")
        self._line_count = 0
        for line in all_lines:
            if line:
                if self._filter_text and self._filter_text.lower() not in line.lower():
                    continue
                # 尝试根据前缀确定日志级别
                tag = "info"
                for level, t in LEVEL_TAGS.items():
                    if f"[{level}]" in line:
                        tag = t
                        break
                self._text.insert("end", line + "\n", tag)
                self._line_count += 1
        self._text.configure(state="disabled")
        if self._auto_scroll:
            self._text.see("end")
        self._log_count_label.configure(text=f"{self._line_count} 条/{old_count} 总计")

    def refresh(self):
        """拉取新日志并追加到显示。"""
        records = self._handler.get_all()
        if not records:
            return

        self._text.configure(state="normal")

        for record in records:
            line = record.formatted

            # 搜索过滤
            if self._filter_text:
                if self._filter_text.lower() not in line.lower():
                    continue

            # 插入日志行
            tag = LEVEL_TAGS.get(record.levelname, "info")
            self._text.insert("end", line + "\n", tag)

            self._line_count += 1

            # 限制最大行数
            if self._line_count > self._max_lines:
                first_line_end = self._text.search(
                    "\n", "1.0", stopindex="2.0"
                )
                if first_line_end:
                    self._text.delete("1.0", first_line_end + "+1c")
                    self._line_count -= 1

        # 自动滚动到底部
        if self._auto_scroll:
            self._text.see("end")

        self._text.configure(state="disabled")
        total_lines = max(1, int(self._text.index("end-1c").split(".")[0]))
        if self._filter_text:
            self._log_count_label.configure(text=f"{self._line_count} 条/{total_lines} 总计")
        else:
            self._log_count_label.configure(text=f"{self._line_count} 条")
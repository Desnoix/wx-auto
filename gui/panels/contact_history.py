"""
联系人回复历史面板 — 显示已回复的联系人列表。

支持：
  - 表格视图：时间、联系人、回复内容
  - 自动刷新
  - 清空历史
"""

import tkinter as tk
from typing import Optional

import customtkinter as ctk

from ..engine_thread import EngineState


class ContactHistoryPanel(ctk.CTkFrame):
    """联系人回复历史表格面板。"""

    def __init__(self, master, engine_state: EngineState):
        super().__init__(master)
        self.engine_state = engine_state
        self._last_history_len = 0  # 避免每 500ms 全量重建

        self._build_toolbar()
        self._build_table()

    # ---- 构建 ----

    def _build_toolbar(self):
        toolbar = ctk.CTkFrame(self, height=40, corner_radius=6)
        toolbar.pack(fill="x", padx=8, pady=(8, 4))
        toolbar.pack_propagate(False)

        ctk.CTkLabel(
            toolbar, text="回复历史记录",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left", padx=(12, 8))

        ctk.CTkLabel(toolbar, text="").pack(side="left", fill="x", expand=True)

        self._count_label = ctk.CTkLabel(
            toolbar, text="0 条记录", font=ctk.CTkFont(size=12),
            text_color="#90A4AE",
        )
        self._count_label.pack(side="right", padx=8)

        self._clear_btn = ctk.CTkButton(
            toolbar, text="🗑 清空", width=70, height=28,
            fg_color="#546E7A", hover_color="#455A64",
            command=self._clear_history,
        )
        self._clear_btn.pack(side="right", padx=4)

    def _build_table(self):
        """构建表格视图。"""
        container = ctk.CTkFrame(self)
        container.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        # 表头
        header = ctk.CTkFrame(container, height=32, corner_radius=4)
        header.pack(fill="x")
        header.pack_propagate(False)

        col_widths = [150, 120, 1]
        col_titles = ["时间", "联系人", "回复内容"]

        for i, (w, t) in enumerate(zip(col_widths, col_titles)):
            ctk.CTkLabel(
                header, text=t,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#90A4AE",
                width=w if w > 1 else 0,
            ).pack(side="left", padx=(8 if i == 0 else 4, 0), fill="x" if w == 1 else "none",
                   expand=(w == 1))

        # 分隔线
        ctk.CTkFrame(container, height=1, fg_color="#37474F").pack(fill="x")

        # 可滚动的列表区域
        self._list_frame = ctk.CTkScrollableFrame(container)
        self._list_frame.pack(fill="both", expand=True)

        # 占位文字
        self._empty_label = ctk.CTkLabel(
            self._list_frame, text="暂无回复记录",
            font=ctk.CTkFont(size=13), text_color="#616161",
        )
        self._empty_label.pack(expand=True, pady=40)

    # ---- 数据 ----

    def refresh(self):
        """刷新表格数据（增量更新，避免每 500ms 全量重建）。"""
        if self.engine_state is None:
            return
        history = self.engine_state.get("contact_history", [])

        # 长度未变化时跳过全量重建
        if len(history) == self._last_history_len and not (
            not history and self._list_frame.winfo_children()
        ):
            return

        self._last_history_len = len(history)

        if not history:
            for w in self._list_frame.winfo_children():
                w.destroy()
            self._empty_label = ctk.CTkLabel(
                self._list_frame, text="暂无回复记录",
                font=ctk.CTkFont(size=13), text_color="#616161",
            )
            self._empty_label.pack(expand=True, pady=40)
            self._count_label.configure(text="0 条记录")
            return

        # 重建行（只显示最近 200 条）
        display = history[-200:]

        for w in self._list_frame.winfo_children():
            w.destroy()

        for record in reversed(display):
            row = ctk.CTkFrame(self._list_frame, fg_color="transparent", height=28)
            row.pack(fill="x", pady=1)
            row.pack_propagate(False)

            ctk.CTkLabel(
                row, text=record.get("time", ""),
                font=ctk.CTkFont(size=11), text_color="#78909C",
                width=150,
            ).pack(side="left", padx=(8, 4))

            ctk.CTkLabel(
                row, text=record.get("contact", ""),
                font=ctk.CTkFont(size=12, weight="bold"),
                width=120,
            ).pack(side="left", padx=4)

            reply = record.get("reply", "")
            ctk.CTkLabel(
                row, text=reply,
                font=ctk.CTkFont(size=11), text_color="#B0BEC5",
                anchor="w",
            ).pack(side="left", padx=4, fill="x", expand=True)

        self._count_label.configure(text=f"{len(display)} 条记录")

    def _clear_history(self):
        """清空历史。"""
        self.engine_state.set("contact_history", [])
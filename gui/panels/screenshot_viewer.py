"""
截图查看器面板 — 浏览和预览微信自动回复的截图。

支持：
  - 缩略图网格浏览
  - 点击放大查看
  - 按日期分组
  - 刷新
"""

import os
from pathlib import Path
from typing import Optional

import customtkinter as ctk
from PIL import Image

try:
    from ..theme import c
except ImportError:
    from gui.theme import c

# 缩略图尺寸
THUMB_SIZE = (180, 130)


class ScreenshotViewerPanel(ctk.CTkFrame):
    """截图查看器面板。"""

    def __init__(self, master, screenshot_dir: str = "screenshots"):
        super().__init__(master)
        self._screenshot_dir = screenshot_dir
        self._thumbnails: list[dict] = []
        self._preview_window: Optional[ctk.CTkToplevel] = None
        self._known_files: list[str] = []

        self._build_toolbar()
        self._build_grid()

    # ---- 构建 ----

    def _build_toolbar(self):
        toolbar = ctk.CTkFrame(self, height=40, corner_radius=6)
        toolbar.pack(fill="x", padx=8, pady=(8, 4))
        toolbar.pack_propagate(False)

        ctk.CTkLabel(
            toolbar, text="截图浏览器",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left", padx=(12, 8))

        ctk.CTkLabel(toolbar, text="").pack(side="left", fill="x", expand=True)

        self._count_label = ctk.CTkLabel(
            toolbar, text="0 张截图", font=ctk.CTkFont(size=12),
            text_color=c("text_med"),
        )
        self._count_label.pack(side="right", padx=8)

        self._refresh_btn = ctk.CTkButton(
            toolbar, text="⟳ 刷新", width=70, height=28,
            fg_color=c("surface_2"), hover_color=c("border_strong"),
            text_color=c("text_hi"),
            command=self._force_refresh,
        )
        self._refresh_btn.pack(side="right", padx=4)

    def _build_grid(self):
        """可滚动的缩略图网格。"""
        self._scroll_frame = ctk.CTkScrollableFrame(self)
        self._scroll_frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))

    # ---- 数据加载 ----

    def _force_refresh(self):
        """强制刷新：清除缓存重建。"""
        self._known_files = []
        self.refresh()

    def refresh(self):
        """增量刷新：仅当文件列表变化时重建。"""
        screenshot_path = Path(self._screenshot_dir)

        if not screenshot_path.is_dir():
            if self._known_files:
                self._known_files = []
                for widget in self._scroll_frame.winfo_children():
                    widget.destroy()
            self._count_label.configure(text="截图目录不存在")
            return

        png_files = sorted(
            screenshot_path.glob("*.png"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        current_files = [str(f) for f in png_files]
        if current_files == self._known_files:
            return

        self._known_files = current_files

        for widget in self._scroll_frame.winfo_children():
            widget.destroy()

        self._thumbnails = []

        if not png_files:
            self._count_label.configure(text="没有截图")
            return

        self._count_label.configure(text=f"{len(png_files)} 张截图")
        self._render_thumbnails(png_files)

    def _render_thumbnails(self, files: list[Path]):
        """渲染缩略图网格。"""
        widget_width = self._scroll_frame.winfo_width()
        if widget_width <= 1:
            cols = 4
        else:
            cols = max(1, widget_width // (THUMB_SIZE[0] + 16))

        current_row_frame = None

        for idx, filepath in enumerate(files):
            if idx % cols == 0:
                current_row_frame = ctk.CTkFrame(self._scroll_frame, fg_color="transparent")
                current_row_frame.pack(fill="x", pady=2)

            thumb_frame = ctk.CTkFrame(
                current_row_frame, width=THUMB_SIZE[0] + 20,
                height=THUMB_SIZE[1] + 40, corner_radius=6,
            )
            thumb_frame.pack(side="left", padx=4, pady=2)
            thumb_frame.pack_propagate(False)

            try:
                img = Image.open(filepath)
                img.thumbnail(THUMB_SIZE, Image.LANCZOS)

                bg = Image.new("RGB", THUMB_SIZE, (30, 30, 30))
                offset = (
                    (THUMB_SIZE[0] - img.width) // 2,
                    (THUMB_SIZE[1] - img.height) // 2,
                )
                bg.paste(img, offset)
                photo = ctk.CTkImage(light_image=bg, dark_image=bg, size=THUMB_SIZE)

                img_label = ctk.CTkLabel(
                    thumb_frame, image=photo, text="", cursor="hand2",
                )
                img_label.image = photo
                img_label.pack(padx=6, pady=(6, 2))

                img_path_str = str(filepath)
                img_label.bind(
                    "<Button-1>",
                    lambda e, p=img_path_str: self._show_preview(p),
                )

                name_label = ctk.CTkLabel(
                    thumb_frame,
                    text=filepath.name[:25] + ("..." if len(filepath.name) > 25 else ""),
                    font=ctk.CTkFont(size=9), text_color=c("text_low"),
                )
                name_label.pack(padx=4, pady=(0, 4))

            except Exception:
                ctk.CTkLabel(
                    thumb_frame, text="加载失败",
                    font=ctk.CTkFont(size=9), text_color=c("error"),
                ).pack(expand=True)

    # ---- 预览 ----

    def _show_preview(self, filepath: str):
        """在新窗口显示完整尺寸截图。"""
        if self._preview_window is not None:
            try:
                self._preview_window.destroy()
            except Exception:
                pass

        self._preview_window = ctk.CTkToplevel(self)
        self._preview_window.title(f"截图预览 — {os.path.basename(filepath)}")
        self._preview_window.geometry("800x600")

        try:
            img = Image.open(filepath)
            max_w, max_h = 1600, 1200
            img.thumbnail((max_w, max_h), Image.LANCZOS)
            photo = ctk.CTkImage(light_image=img, dark_image=img,
                                  size=(img.width, img.height))

            label = ctk.CTkLabel(
                self._preview_window, image=photo, text="",
            )
            label.image = photo
            label.pack(fill="both", expand=True, padx=10, pady=10)

        except Exception as e:
            ctk.CTkLabel(
                self._preview_window, text=f"无法加载图片: {e}",
                font=ctk.CTkFont(size=14),
            ).pack(expand=True)
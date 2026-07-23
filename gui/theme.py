"""
主题系统 — 支持 Light / Dark 两套配色。

用法：
    from gui.theme import c, resolve, set_mode, on_theme_change

    # CTk 控件：使用 tuple 颜色，appearance_mode 切换时自动跟随
    ctk.CTkFrame(parent, fg_color=c("surface"))

    # 非 CTk 控件（如 tk.Text）：手动 resolve + 注册钩子
    text.configure(bg=resolve("editor_bg"))
    on_theme_change(lambda mode: text.configure(bg=resolve("editor_bg")))
"""

from typing import Callable

import customtkinter as ctk


# ---- 双主题调色板：(light, dark) ----
PALETTE: dict[str, tuple[str, str]] = {
    # 表面
    "bg":            ("#FFFFFF", "#0E1117"),
    "sidebar_bg":    ("#F6F8FA", "#0B0E13"),
    "surface":       ("#F6F8FA", "#161B22"),
    "surface_2":     ("#EAEEF2", "#1C232B"),
    "surface_3":     ("#DDE3E8", "#252C34"),
    "border":        ("#D0D7DE", "#21262D"),
    "border_strong": ("#AFB8C1", "#30363D"),
    # 文字
    "text_hi":       ("#1F2328", "#E6EDF3"),
    "text_med":      ("#656D76", "#8B949E"),
    "text_low":      ("#8C959F", "#6E7681"),
    "text_inverse":  ("#FFFFFF", "#0E1117"),
    # 主色
    "accent":        ("#0969DA", "#58A6FF"),
    "accent_hov":    ("#0550AE", "#79B8FF"),
    "accent_text":   ("#FFFFFF", "#0E1117"),
    # 语义色
    "success":       ("#1A7F37", "#3FB950"),
    "success_bg":    ("#DAFBE1", "#0F2E1A"),
    "success_text":  ("#0A4A1F", "#B7E4C7"),
    "warning":       ("#9A6700", "#D29922"),
    "warning_bg":    ("#FFF8C5", "#332810"),
    "warning_text":  ("#7A5100", "#F5D28A"),
    "error":         ("#CF222E", "#F85149"),
    "error_bg":      ("#FFEBE9", "#3C1618"),
    "error_text":    ("#82071E", "#FFB4AB"),
    "error_hov":     ("#B41F26", "#5A1D20"),
    # 编辑器（日志区）
    "editor_bg":     ("#FFFFFF", "#0A0D12"),
    "editor_text":   ("#1F2328", "#E6EDF3"),
    # 搜索高亮
    "hl_bg":         ("#FFF8C4", "#3D2E00"),
    "hl_fg":         ("#4D3C00", "#F0E68C"),
    # 装饰点色
    "dot_blue":      ("#0969DA", "#79C0FF"),
    "dot_orange":    ("#BC4C00", "#FFB454"),
    "dot_green":     ("#1A7F37", "#7EE787"),
    "dot_teal":      ("#118D8B", "#56D4CE"),
    "dot_purple":    ("#8250DF", "#D2A8FF"),
    "dot_yellow":    ("#9A6700", "#F0E68C"),
}


def c(name: str) -> tuple[str, str]:
    """返回 (light, dark) 元组，直接用于 CTk 颜色参数。"""
    return PALETTE[name]


def resolve(name: str, mode: str | None = None) -> str:
    """基于当前 appearance mode 返回单一颜色（用于 tk.Text 等非 CTk 部件）。"""
    if mode is None:
        mode = ctk.get_appearance_mode()
    idx = 0 if str(mode).lower().startswith("l") else 1
    return PALETTE[name][idx]


# ---- 主题变更钩子 ----

_hooks: list[Callable[[str], None]] = []


def on_theme_change(fn: Callable[[str], None]) -> None:
    """注册主题变更回调。fn(mode) 会在 set_mode 后被调用。"""
    _hooks.append(fn)


def set_mode(mode: str) -> None:
    """切换主题。mode ∈ {'light', 'dark'}"""
    mode = mode.lower()
    if mode not in ("light", "dark"):
        raise ValueError(mode)
    ctk.set_appearance_mode(mode)
    for fn in list(_hooks):
        try:
            fn(mode)
        except Exception:
            pass


def current_mode() -> str:
    """返回当前主题字符串 'light' 或 'dark'。"""
    return "light" if str(ctk.get_appearance_mode()).lower().startswith("l") else "dark"


# ---- 日志级别样式 ----

LEVEL_STYLE: dict[str, dict] = {
    "CRITICAL": {
        "badge_bg":   ("#B62324", "#DA3633"),
        "badge_fg":   ("#FFFFFF", "#FFFFFF"),
        "msg_fg":     ("#B62324", "#FFA198"),
        "short":      "CRIT",
    },
    "ERROR": {
        "badge_bg":   ("#CF222E", "#F85149"),
        "badge_fg":   ("#FFFFFF", "#FFFFFF"),
        "msg_fg":     ("#CF222E", "#FFA198"),
        "short":      "ERR ",
    },
    "WARNING": {
        "badge_bg":   ("#BF8700", "#D29922"),
        "badge_fg":   ("#FFFFFF", "#0E1117"),
        "msg_fg":     ("#9A6700", "#F0B84A"),
        "short":      "WARN",
    },
    "INFO": {
        "badge_bg":   ("#0969DA", "#58A6FF"),
        "badge_fg":   ("#FFFFFF", "#0E1117"),
        "msg_fg":     ("#1F2328", "#C9D1D9"),
        "short":      "INFO",
    },
    "DEBUG": {
        "badge_bg":   ("#8C959F", "#30363D"),
        "badge_fg":   ("#FFFFFF", "#C9D1D9"),
        "msg_fg":     ("#656D76", "#8B949E"),
        "short":      "DBG ",
    },
}


def level_color(level: str, key: str) -> str:
    """返回日志级别在当前主题下的单色（用于 tk.Text tag）。"""
    style = LEVEL_STYLE.get(level, LEVEL_STYLE["INFO"])
    val = style[key]
    if isinstance(val, tuple):
        idx = 0 if current_mode() == "light" else 1
        return val[idx]
    return val

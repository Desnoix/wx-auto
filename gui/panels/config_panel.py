"""
配置编辑器面板 — 可视化编辑 config.yaml 的关键字段。
"""

import os
import re
import tkinter as tk
from typing import Optional

import customtkinter as ctk
import yaml

try:
    from ..theme import c
except ImportError:
    from gui.theme import c


class ConfigPanel(ctk.CTkFrame):
    """配置编辑面板。"""

    def __init__(self, master, config_path: str):
        super().__init__(master)
        self._config_path = config_path
        self._config: dict = {}
        self._original_config: dict = {}

        # 入口字段引用
        self._llm_base_url: Optional[ctk.CTkEntry] = None
        self._llm_api_key: Optional[ctk.CTkEntry] = None
        self._llm_model: Optional[ctk.CTkEntry] = None
        self._llm_timeout: Optional[ctk.CTkEntry] = None
        self._llm_temp_slider: Optional[ctk.CTkSlider] = None
        self._llm_temp_label: Optional[ctk.CTkLabel] = None
        self._auto_reply_cooldown: Optional[ctk.CTkEntry] = None
        self._auto_poll_interval: Optional[ctk.CTkEntry] = None
        self._auto_click_delay: Optional[ctk.CTkEntry] = None
        self._auto_send_delay: Optional[ctk.CTkEntry] = None
        self._sm_max_cycles: Optional[ctk.CTkEntry] = None
        self._sm_idle_cooldown: Optional[ctk.CTkEntry] = None
        self._cap_save_switch: Optional[ctk.CTkSwitch] = None
        self._cap_screenshot_dir: Optional[ctk.CTkEntry] = None
        self._cap_save_var = tk.BooleanVar(value=True)
        self._ignore_textbox: Optional[ctk.CTkTextbox] = None

        self._save_status: Optional[ctk.CTkLabel] = None

        # 可滚动容器
        self._scroll_area = ctk.CTkScrollableFrame(self)
        self._scroll_area.pack(fill="both", expand=True, padx=8, pady=8)

        self._build_sections()

        self._load_config()
        self._update_ui()

    # ---- 构建方法 ----

    def _build_sections(self):
        """构建所有配置区块。"""
        self._build_llm_section()
        self._build_automation_section()
        self._build_ignore_section()
        self._build_state_machine_section()
        self._build_capture_section()
        self._build_action_bar()

    def _make_section(self, title: str, subtitle: str = "") -> ctk.CTkFrame:
        """创建一个配置区块。"""
        # 标题
        header = ctk.CTkFrame(self._scroll_area, fg_color="transparent")
        header.pack(fill="x", pady=(16, 2))

        ctk.CTkLabel(
            header, text=title,
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(anchor="w")

        if subtitle:
            ctk.CTkLabel(
                header, text=subtitle,
                font=ctk.CTkFont(size=11), text_color=c("text_med"),
            ).pack(anchor="w")

        # 内容框
        frame = ctk.CTkFrame(self._scroll_area, corner_radius=8)
        frame.pack(fill="x", padx=0, pady=(4, 8))
        frame.columnconfigure(0, minsize=160)
        frame.columnconfigure(1, weight=1)

        return frame

    def _add_entry(self, parent, row: int, label: str,
                   placeholder: str = "", show: str = "") -> ctk.CTkEntry:
        """在区块中添加一行文本输入。"""
        ctk.CTkLabel(
            parent, text=label, font=ctk.CTkFont(size=12), anchor="w",
        ).grid(row=row, column=0, sticky="w", padx=(12, 8), pady=5)

        var = ctk.StringVar()
        entry = ctk.CTkEntry(
            parent, textvariable=var, height=30,
            placeholder_text=placeholder, show=show,
        )
        entry.grid(row=row, column=1, sticky="ew", padx=(0, 12), pady=5)

        return entry

    def _build_llm_section(self):
        """LLM 配置区域。"""
        frame = self._make_section("LLM 配置", "OpenAI 兼容接口配置")

        self._llm_base_url = self._add_entry(
            frame, 0, "Base URL", "例如 https://api.openai.com/v1"
        )
        self._llm_api_key = self._add_entry(
            frame, 1, "API Key", "你的 API 密钥", show="*"
        )
        self._llm_model = self._add_entry(
            frame, 2, "Model", "例如 gpt-4o-mini"
        )
        self._llm_timeout = self._add_entry(
            frame, 3, "Timeout (秒)", "请求超时时间，默认 60"
        )

        # Temperature
        ctk.CTkLabel(
            frame, text="Temperature", font=ctk.CTkFont(size=12),
        ).grid(row=4, column=0, sticky="w", padx=(12, 8), pady=5)

        slider_row = ctk.CTkFrame(frame, fg_color="transparent")
        slider_row.grid(row=4, column=1, sticky="ew", padx=(0, 12), pady=5)

        self._llm_temp_var = tk.DoubleVar(value=0.7)
        self._llm_temp_slider = ctk.CTkSlider(
            slider_row, from_=0.0, to=2.0, number_of_steps=20,
            variable=self._llm_temp_var, width=200,
        )
        self._llm_temp_slider.pack(side="left")

        self._llm_temp_label = ctk.CTkLabel(
            slider_row, text="0.7", font=ctk.CTkFont(size=11), width=30
        )
        self._llm_temp_label.pack(side="left", padx=(8, 0))

        self._llm_temp_var.trace_add(
            "write", lambda *a: self._llm_temp_label.configure(
                text=f"{self._llm_temp_var.get():.1f}"
            )
        )

    def _build_automation_section(self):
        """自动化配置区域。"""
        frame = self._make_section("自动化配置", "鼠标、键盘和冷却设置")

        self._auto_reply_cooldown = self._add_entry(
            frame, 0, "回复冷却 (秒)", "同一联系人最小回复间隔"
        )
        self._auto_poll_interval = self._add_entry(
            frame, 1, "轮询间隔 (秒)", "两次监控扫描之间的等待时间"
        )
        self._auto_click_delay = self._add_entry(
            frame, 2, "点击延迟 (秒)", "鼠标按下/抬起之间的延迟"
        )
        self._auto_send_delay = self._add_entry(
            frame, 3, "发送后延迟 (秒)", "发送后等待验证的时间"
        )

    def _build_ignore_section(self):
        """忽略联系人配置区域。"""
        frame = self._make_section("忽略联系人", "命中任一关键词即跳过，不自动回复（每行一个）")

        self._ignore_textbox = ctk.CTkTextbox(frame, height=120, font=ctk.CTkFont(size=12))
        self._ignore_textbox.pack(fill="x", padx=12, pady=8)

    def _build_state_machine_section(self):
        """状态机配置区域。"""
        frame = self._make_section("状态机配置", "重试和周期限制")

        self._sm_max_cycles = self._add_entry(
            frame, 0, "每联系人最大周期", "超过此次数后丢弃联系人"
        )
        self._sm_idle_cooldown = self._add_entry(
            frame, 1, "IDLE 冷却 (秒)", "IDLE→MONITOR 转换间隔"
        )

    def _build_capture_section(self):
        """截图配置区域。"""
        frame = self._make_section("截图配置", "截图的保存和显示设置")

        ctk.CTkLabel(
            frame, text="保存截图", font=ctk.CTkFont(size=12),
        ).grid(row=0, column=0, sticky="w", padx=(12, 8), pady=5)

        self._cap_save_switch = ctk.CTkSwitch(
            frame, text="", variable=self._cap_save_var,
        )
        self._cap_save_switch.grid(row=0, column=1, sticky="w", padx=(0, 12), pady=5)

        self._cap_screenshot_dir = self._add_entry(
            frame, 1, "截图目录", "保存截图的文件夹"
        )

    def _build_action_bar(self):
        """底部操作栏。"""
        bar = ctk.CTkFrame(self._scroll_area, height=50, corner_radius=6)
        bar.pack(fill="x", pady=(8, 4))
        bar.pack_propagate(False)

        self._save_status = ctk.CTkLabel(
            bar, text="", font=ctk.CTkFont(size=12), text_color=c("success")
        )
        self._save_status.pack(side="left", padx=16)

        ctk.CTkLabel(bar, text="").pack(side="left", fill="x", expand=True)

        ctk.CTkButton(
            bar, text="保存配置", width=120, height=32,
            fg_color=c("accent"), hover_color=c("accent_hov"),
            text_color=c("accent_text"),
            command=self._save_config,
        ).pack(side="right", padx=10)

        ctk.CTkButton(
            bar, text="重置", width=80, height=32,
            fg_color=c("surface_2"), hover_color=c("border_strong"),
            text_color=c("text_hi"),
            command=self._reset_config,
        ).pack(side="right", padx=4)

        ctk.CTkButton(
            bar, text="重新加载", width=100, height=32,
            fg_color=c("surface_2"), hover_color=c("border_strong"),
            text_color=c("text_hi"),
            command=self._reload_config,
        ).pack(side="right", padx=4)

    # ---- 数据加载与保存 ----

    def _load_config(self):
        """从文件加载配置。"""
        try:
            with open(self._config_path, encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
            self._original_config = dict(self._config)
        except Exception:
            self._config = {}
            self._original_config = {}

    def _update_ui(self):
        """用加载的配置更新 UI 控件。"""
        def _set_entry(entry, value):
            if entry:
                entry.delete(0, "end")
                entry.insert(0, str(value))

        def _get_val(keys, default=""):
            d = self._config
            for k in keys:
                if isinstance(d, dict):
                    d = d.get(k)
                else:
                    return default
            return d if d is not None else default

        _set_entry(self._llm_base_url, _get_val(["llm", "base_url"], ""))
        _set_entry(self._llm_api_key, _get_val(["llm", "api_key"], ""))
        _set_entry(self._llm_model, _get_val(["llm", "model"], ""))
        _set_entry(self._llm_timeout, str(_get_val(["llm", "timeout"], 60)))
        self._llm_temp_var.set(_get_val(["llm", "temperature"], 0.7))

        _set_entry(self._auto_reply_cooldown, str(_get_val(["automation", "reply_cooldown"], 30)))
        _set_entry(self._auto_poll_interval, str(_get_val(["monitor", "poll_interval"], 1.0)))
        _set_entry(self._auto_click_delay, str(_get_val(["automation", "click_delay"], 0.3)))
        _set_entry(self._auto_send_delay, str(_get_val(["automation", "send_delay"], 1.0)))
        _set_entry(self._sm_max_cycles, str(_get_val(["state_machine", "max_cycles_per_chat"], 3)))
        _set_entry(self._sm_idle_cooldown, str(_get_val(["state_machine", "idle_cooldown"], 0.5)))
        self._cap_save_var.set(_get_val(["capture", "save_screenshots"], True))
        _set_entry(self._cap_screenshot_dir, _get_val(["capture", "screenshot_dir"], "screenshots"))

        if self._ignore_textbox:
            self._ignore_textbox.delete("1.0", "end")
            ignore_list = _get_val(["automation", "ignore_contacts"], []) or []
            self._ignore_textbox.insert("1.0", "\n".join(str(s) for s in ignore_list))

    def _save_config(self):
        """将 UI 值保存到配置文件（保留注释和格式）。

        使用逐行替换的方式编辑 YAML，避免 yaml.dump 丢失注释。
        """
        try:
            # 读取 UI 值
            def _get_entry(entry):
                return entry.get() if entry else ""

            new_values: dict[str, str] = {}

            def _add_val(yaml_key: str, ui_value) -> None:
                new_values[yaml_key] = str(ui_value)

            _add_val("base_url:", _get_entry(self._llm_base_url))
            _add_val("api_key:", _get_entry(self._llm_api_key))
            _add_val("model:", _get_entry(self._llm_model))
            _add_val("temperature:", round(self._llm_temp_var.get(), 1))
            try:
                _add_val("timeout:", int(_get_entry(self._llm_timeout)))
            except ValueError:
                pass

            try:
                _add_val("reply_cooldown:", int(_get_entry(self._auto_reply_cooldown)))
                _add_val("poll_interval:", float(_get_entry(self._auto_poll_interval)))
                _add_val("click_delay:", float(_get_entry(self._auto_click_delay)))
                _add_val("send_delay:", float(_get_entry(self._auto_send_delay)))
                _add_val("max_cycles_per_chat:", int(_get_entry(self._sm_max_cycles)))
                _add_val("idle_cooldown:", float(_get_entry(self._sm_idle_cooldown)))
            except ValueError:
                self._save_status.configure(text="✗ 数值格式错误", text_color=c("error"))
                return

            _add_val("save_screenshots:", str(self._cap_save_var.get()).lower())
            _add_val("screenshot_dir:", _get_entry(self._cap_screenshot_dir))

            # 逐行读取并替换值（保留注释）
            with open(self._config_path, encoding="utf-8") as f:
                lines = f.readlines()

            modified = False
            for i, line in enumerate(lines):
                stripped = line.strip()
                # 跳过注释行和空行
                if not stripped or stripped.startswith("#"):
                    continue
                # 检查是否匹配任何已知 key
                for key, new_val in new_values.items():
                    # 匹配 "key: value" 模式
                    pattern = re.compile(r'^(\s*)(' + re.escape(key) + r'\s*)(.*?)(\s*#.*)?$')
                    m = pattern.match(line)
                    if m:
                        indent = m.group(1)
                        key_part = m.group(2)
                        comment = m.group(4) or ""
                        old_val = m.group(3).strip()
                        if old_val != new_val:
                            # 对需要引号的值进行 YAML 安全转义
                            safe_val = self._yaml_quote_value(new_val, key)
                            lines[i] = f"{indent}{key_part}{safe_val}{comment}\n"
                            modified = True
                        break

            if modified:
                with open(self._config_path, "w", encoding="utf-8") as f:
                    f.writelines(lines)

            # 保存 ignore_contacts 列表（需要特殊处理 YAML 列表）
            if self._ignore_textbox:
                new_items = [
                    s.strip() for s in self._ignore_textbox.get("1.0", "end").splitlines()
                    if s.strip()
                ]
                with open(self._config_path, encoding="utf-8") as f:
                    lines = f.readlines()

                # 找到 ignore_contacts: 行，替换其后续的列表项
                start_idx = None
                for i, line in enumerate(lines):
                    if line.strip().startswith("ignore_contacts:"):
                        start_idx = i
                        break

                if start_idx is not None:
                    # 删除旧的列表项
                    end_idx = start_idx + 1
                    while end_idx < len(lines) and lines[end_idx].strip().startswith("- "):
                        end_idx += 1
                    # 获取缩进（列表项比 key 多两格）
                    key_indent = len(lines[start_idx]) - len(lines[start_idx].lstrip())
                    item_indent = " " * (key_indent + 4)
                    new_lines = [f'{item_indent}- "{item}"\n' for item in new_items]
                    lines[start_idx + 1:end_idx] = new_lines

                    with open(self._config_path, "w", encoding="utf-8") as f:
                        f.writelines(lines)

            self._save_status.configure(text="✓ 配置已保存", text_color=c("success"))
            self.after(3000, lambda: self._save_status.configure(text=""))

        except Exception as e:
            self._save_status.configure(text=f"✗ 保存失败: {e}", text_color=c("error"))

    def _reload_config(self):
        """重新从文件加载配置。"""
        self._load_config()
        self._update_ui()
        self._save_status.configure(text="⟳ 配置已重新加载", text_color=c("accent"))
        self.after(3000, lambda: self._save_status.configure(text=""))

    def _reset_config(self):
        """重置为上次保存的值（从文件重新加载）。"""
        self._load_config()
        self._update_ui()
        self._save_status.configure(text="↩ 已重置为已保存值", text_color=c("warning"))
        self.after(3000, lambda: self._save_status.configure(text=""))

    def reload_config(self):
        """公开方法：重新从文件加载配置。"""
        self._reload_config()

    @staticmethod
    def _yaml_quote_value(val: str, key: str) -> str:
        """对 YAML 值进行安全转义。数字和布尔值保持原样，字符串添加引号。

        Args:
            val: 要写入的原始值字符串。
            key: 配置键（用于判断值类型）。

        Returns:
            YAML 安全的值字符串。
        """
        # 布尔值和数字保持原样
        if val in ("true", "false", "True", "False"):
            return val.lower()
        try:
            float(val)
            return val
        except ValueError:
            pass
        # 空字符串保留为空
        if not val:
            return '""'
        # 字符串包含特殊字符时加引号
        special_chars = set(':#{}[]&*!|>%`@"\'')
        if any(c in val for c in special_chars) or " " in val:
            # 转义内部双引号和反斜杠
            escaped = val.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        return val
# WeChat Auto-Reply — Agent 指南

Windows-only Python 3.10+ 项目。微信 PC 4.x 自动回复，技术路线：**后台截图 → OCR → LLM → 剪贴板粘贴**——无 Hook、无 DLL 注入、无协议逆向。

## 快速开始

```bash
pip install -r requirements.txt
# 编辑 config/config.yaml — 设置 llm.base_url + llm.api_key
python main.py       # Ctrl+C 停止
```

启动前微信必须已登录。程序会自动查找微信窗口。

## 架构

**`main.py` 是"容器型"入口**——从配置组装所有组件并运行状态机循环。所有模块都在这一个文件里完成接线（第 89–173 行）。如需添加新组件，在这里接上。

```
main.py                # 入口：组件组装 + 主循环
config/config.yaml     # 10 个配置段，只有 llm.* 需要用户输入
capture/               # PrintWindow 后台截图（无需前台窗口）
ocr/                   # RapidOCR onnxruntime 引擎（懒加载，用于联系人定位）
detector/              # VL 未读检测、联系人定位（OCR）、消息提取
llm/                   # OpenAI 兼容提供者（支持文本 + 图片分析）
automation/            # 鼠标（ClientToScreen）+ 键盘（剪贴板粘贴）
monitor/               # 定时 OCR 扫描左侧面板（无 phash，当前为空）
taskqueue/             # 线程安全 FIFO 未读联系人队列
state/                 # 驱动工作流的 10 状态状态机
recovery/              # 看门狗线程：进程健康、卡死检测、磁盘清理
```

## 必知：坐标系

这是 #1 易错点。所有坐标都是**客户区相对坐标**：

1. `PrintWindow(hwnd, PW_CLIENTONLY)` 只捕获客户区（无标题栏/边框）
2. OCR 返回的边界框坐标相对于截取的图片（即客户区坐标）
3. 鼠标点击通过 `win32api.ClientToScreen(hwnd, (x, y))` 转换——**绝对不要**自己用 `GetWindowRect` 算偏移

配置中的比例裁剪区域（如 `0.30` = 客户区宽度的 30%）与此一致。

## 状态机

10 个状态，线性推进，带错误恢复：

```
IDLE → MONITOR → DETECT_UNREAD → OPEN_CHAT → READ_MESSAGE
  → GENERATE_REPLY → SEND → VERIFY → COMPLETE / ERROR → IDLE
```

关键行为：
- **回复冷却**：每个联系人 30 秒（可配置 `automation.reply_cooldown`）。防止循环。
- **最大重试**：每个状态内最多 3 次；每个联系人最多 3 个完整周期（`state_machine.max_cycles_per_chat`），超限则丢弃。
- **卡死检测**：看门狗在同一状态持续超过 `watchdog.max_stuck_cycles`（默认 10）时强制转入 ERROR。
- **队列**：跨联系人的 FIFO，按名称去重。

## 关键注意事项

- **微信窗口类名**（`Qt51514QWindowIcon`）跟版本绑定，仅限微信 4.x。版本更新后如果改了类名，更新 `config.yaml wechat.class_name`。
- **RapidOCR 输出格式**：`result[0]` 是一个列表，每个元素为 `[ [[x1,y1],[x2,y2],[x3,y3],[x4,y4]], text_str, confidence_float ]`。OCR 引擎会将其归一化为 `[x1, y1, x2, y2]` 边界框。
- **角色判断**（消息发送者）：文本边界框中心 X < 窗口宽度 65% = 联系人（"user"），≥ 65% = 自己（"assistant"）。依赖微信的左右对齐布局。
- **状态栏干扰**：消息区域裁剪高度止于 85%，以排除输入框。非经验证不要改动。
- **LLM 禁用**：如果 `llm.api_key` 为空/null，`llm_provider` 为 `None`，系统会打警告日志——GENERATE_REPLY 状态会转入 ERROR。
- **VL 检测器**（`detector/vl_detector.py`）：使用视觉语言模型识别未读联系人，搭配 `ContactDetector`（OCR）精确定位坐标后点击。需 LLM 支持多模态（如 GPT-4o、Qwen-VL）。未读检测链路：VL 识别名称 → OCR 获取坐标。
- **看门狗重启**：需要配置 `watchdog.wechat_exe_path`，否则会回退到常见安装路径。自动重启是尽力而为，不保证成功。
- **黑屏检测**：`PrintWindowCapture._is_black_screen()` 使用 95% 像素阈值 + 10 亮度。大面积黑色的截图会重试（最多 3 次）。
- **GDI 资源清理**：`_capture_single` 中使用 `try/finally` 确保 HDC 和 HBITMAP 释放。改到这部分的代码时，保留这个清理模式。

## 没有测试

此仓库零测试文件。没有 CI、没有 lint、没有类型检查。验证改动的唯一方式是带着运行中的微信窗口执行 `python main.py`，观察日志。

## 依赖（共 8 个）

```
pywin32 pillow pyautogui pyperclip rapidocr_onnxruntime imagehash pyyaml openai
```

除了 `rapidocr_onnxruntime`（~50MB，自带模型）之外都很轻量。首次运行 `main.py` 时惰性加载 OCR 模型。

## 需要关注的配置段

只有 `llm.*` 需要用户输入才能正常运行，其他都有可用的默认值。

| 配置项 | 默认值 | Agent 可能需要改它的场景 |
|---|---|---|
| `wechat.class_name` | `Qt51514QWindowIcon` | 微信版本更新 |
| `monitor.phash_threshold` | 5 | 太高→漏检测变化；太低→误报 |
| `automation.reply_cooldown` | 30 | 调整回复频率容忍度 |
| `watchdog.wechat_exe_path` | "" | 要让自动重启生效就必须设置 |
| `capture.crop_regions.*` | 比例值 | 微信 UI 布局变化 |

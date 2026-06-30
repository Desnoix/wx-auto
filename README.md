# WeChat Auto-Reply 微信自动回复系统

基于 Windows 微信 PC 版（4.x）的智能自动回复系统。采用 **后台截图 + 轻量 OCR + LLM** 的技术路线，无需 Hook、DLL 注入或协议逆向。

---

## 技术路线

| 技术 | 用途 |
|------|------|
| `PrintWindow` + `win32gui` | 后台截图（窗口被遮挡时仍可捕获） |
| VL 多模态模型 | 识别未读联系人（GPT-4o / Qwen-VL） |
| `rapidocr_onnxruntime` | 轻量 OCR（联系人定位、消息提取） |
| `OpenAI SDK` | LLM 回复生成 + 图片分析（兼容任意 OpenAI 接口） |
| `pyautogui` + `pyperclip` | 鼠标点击 + 剪贴板粘贴发送 |
| 状态机 | 驱动全业务流程 |

### 约束条件

- ✅ 不依赖 UIAutomation / pywinauto
- ✅ 不使用 Hook / DLL 注入
- ✅ 不进行协议逆向
- ✅ 不逐字模拟键盘输入（采用剪贴板）
- ✅ **VL 负责识别，OCR 负责定位**——分工明确

---

## 系统架构

```
微信窗口
   ↓
PrintWindow 后台截图
   ↓
VL 识别有未读的联系人 → OCR 精确定位坐标
   ↓ (发现未读)
任务队列调度 → 切换会话 → OCR 提取消息
   ↓
LLM 生成回复 → 剪贴板粘贴发送 → OCR 验证
   ↓ (继续轮询)
```

### 状态机流程

```
IDLE → MONITOR → DETECT_UNREAD → OPEN_CHAT
  → READ_MESSAGE → GENERATE_REPLY → SEND
  → VERIFY → COMPLETE / ERROR → IDLE
```

---

## 项目结构

```
wechat-auto/
├── main.py                      # 入口：组件组装 + 主循环
├── config/config.yaml           # 配置文件（10个配置段）
├── requirements.txt             # 依赖清单
│
├── capture/
│   ├── window_manager.py        # 微信窗口管理（FindWindow/GetWindowRect）
│   └── print_window.py          # PrintWindow 后台截图（GDI→PIL）
│
├── ocr/
│   └── rapid_ocr.py             # RapidOCR 引擎（懒加载、重试、置信度过滤）
│
├── detector/
│   ├── vl_detector.py            # VL 未读联系人识别（多模态模型）
│   ├── contact_detector.py       # 联系人定位（名称→点击坐标）
│   ├── message_detector.py       # 消息提取 + 左右对齐角色判断
│   └── unread_detector.py        # [已弃用] 旧版 OCR 角标匹配
│
├── llm/
│   ├── provider.py              # LLMProvider 抽象基类（含 analyze_image）
│   └── openai_provider.py       # OpenAI 兼容适配器（含视觉 API 支持）
│
├── automation/
│   ├── mouse_controller.py      # 鼠标控制（ClientToScreen 坐标转换）
│   └── keyboard_controller.py   # 键盘控制（剪贴板粘贴，禁止逐字模拟）
│
├── monitor/
│   └── (已清空，原 phash 监控已移除)
│
├── taskqueue/
│   └── task_queue.py            # 线程安全 FIFO 队列
│
├── state/
│   └── state_machine.py         # 状态机核心（10状态 × 10处理器）
│
├── recovery/
│   └── watchdog.py              # 看门狗（崩溃重启 + 卡死恢复 + 磁盘清理）
│
├── screenshots/                 # 截图保存目录
└── logs/                        # 日志目录
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

编辑 `config/config.yaml`：

```yaml
llm:
  base_url: "https://api.openai.com/v1"   # 或 DeepSeek/Qwen/OneAPI 地址
  api_key: "sk-xxx"                        # 你的 API Key
  model: "gpt-4o-mini"                     # 模型名称

prompt:
  system: |
    你是微信自动回复助手。
    要求：
    1. 回复简洁
    2. 不超过50字
    3. 不确定不要编造
    4. 涉及金额转人工
    5. 涉及投诉转人工
```

### 3. 运行

```bash
python main.py
```

确保微信已启动并登录。程序会自动查找微信窗口，进入监控循环。按 `Ctrl+C` 停止。

---

## 配置说明

详见 `config/config.yaml`，主要配置段：

| 配置段 | 说明 |
|--------|------|
| `wechat` | 微信窗口类名（默认 `Qt51514QWindowIcon`） |
| `capture` | 截图目录、裁剪区域比例 |
| `monitor` | 轮询间隔（默认 1s） |
| `ocr` | 引擎、重试次数、置信度阈值 |
| `llm` | API 地址、密钥、模型参数 |
| `prompt` | 系统提示词、最大回复字数 |
| `automation` | 点击/粘贴/发送延迟、回复冷却时间 |
| `state_machine` | 单联系人最大重试周期 |
| `watchdog` | 进程名、崩溃重启路径、卡死检测阈值 |
| `logging` | 日志级别、文件大小、备份数 |

---

## LLM 兼容性

通过 `base_url` 配置支持任意 OpenAI 兼容接口：

| 服务 | `base_url` |
|------|-----------|
| OpenAI | `https://api.openai.com/v1` |
| DeepSeek | `https://api.deepseek.com/v1` |
| 通义千问 Qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| OneAPI / NewAPI | 自定义地址 |
| Gemini（通过 OpenRouter） | `https://openrouter.ai/api/v1` |

无需修改代码，仅改配置即可切换。

---

## 未读检测：VL + OCR 分工

当前版本使用 VL 多模态模型（如 GPT-4o、Qwen-VL）替代旧版 phash + OCR 角标匹配。

- **VL 负责理解**：将整张截图发给多模态模型，模型判断哪些联系人有未读消息，返回联系人名称
- **OCR 负责定位**：对 VL 返回的名称列表，用本地 RapidOCR 在截图左侧面板中精确定位可点击坐标
- **自动化负责执行**：`ClientToScreen` 坐标转换 → `pyautogui` 点击

设计原则：**VL 不直接决定点击坐标，OCR 不负责语义理解**。分工明确，各取所长。

---

## 项目状态

| 里程碑 | 状态 |
|--------|------|
| M1 后台截图 | ✅ 已完成（PrintWindow + GDI→PIL） |
| M2 未读检测 | ✅ 已完成（VL 识别 + OCR 定位） |
| M3 自动切换会话 | ✅ 已完成（OCR定位→点击→标题验证） |
| M4 消息提取 | ✅ 已完成（角色左右对齐判断） |
| M5 自动发送+验证 | ✅ 已完成（剪贴板粘贴 + OCR 子串匹配） |
| M6 LLM 回复生成 | ✅ 已完成（OpenAI 兼容适配器） |
| M7 状态机+队列+恢复 | ✅ 已完成（10状态 + FIFO队列 + 看门狗） |

---

## 技术细节

### 坐标系统

`PrintWindow(hwnd, PW_CLIENTONLY)` 捕获客户端区域内容。OCR 返回的边界框坐标是**客户端区域相对坐标**。鼠标点击通过 `win32gui.ClientToScreen()` 转换为屏幕绝对坐标，确保点击位置精确。

### 消息去重

状态机维护 `_last_reply_contact` 和 `_last_reply_time`。同一联系人在冷却期内（默认30秒）不会被重复处理，防止回复循环。

### 异常恢复

- **OCR 失败**：最多重试3次
- **联系人未找到**：滚动会话列表后重试，最多3次
- **微信崩溃**：看门狗自动重启进程
- **状态机卡死**：看门狗强制转 ERROR → IDLE
- **GDI 泄漏**：资源分配使用 `try/finally` 确保释放
- **截图磁盘溢出**：看门狗自动删除最旧文件

---

## 许可证

MIT
# interview-cheat-tool

面试/测评实时辅助工具（个人备份仓库）。会话制面试助手 + 在线测评/笔试识图快答，双版本源码分支。

> ⚠️ 私有备份用途，请勿公开传播。

## 文件说明

| 文件 | 版本 | 用途 |
|---|---|---|
| `interview-cheat-code.py` | 笔试版 | 手撕代码/算法题：`Alt+P` 截屏识图走「详解」模板（思路/代码/复杂度），`Alt+1` 自动打字进答题框、`Alt+2` 粘贴、`Alt+3` 清识图多轮记忆 |
| `interview-cheat-quiz.py` | 测评版 | 行测/性格测评/选择题：`P`/`F3` 截屏走「测评快答」模板（直接给选项+一句话理由），`max_tokens` 更小、只求快 |
| `interview-cheat-api.py` | 祖本 | 通用分支（不再直接跑），功能与 quiz 版相当（P/F3 识图，无 Alt+ 方案） |
| `hidden-start-quiz.vbs` / `hidden-start-code.vbs` / `hidden-start-chameleon.vbs` | 启动器 | 静默启动（`--chameleon` 无控制台闪窗） |

## 功能链路

- **实时面试**（自动模式，默认开）：双轨录音（回环轨=对方、麦克风轨=自己，外放免耳机）→ 回环 VAD 断句攒问题 → 你开口/停顿自动发送 → 云端转写 → DeepSeek 作答（带历史+简历上下文）→ 屏幕小窗显示；打断自动作废在途答案；全程 WAV + JSONL 落盘复盘。
- **测评/笔试快答**：截图当前题 → 视觉模型直接出答案 → 答案窗显示 + Telegram 推送（F6）+ 可选自动键入（code 版 Alt+1/Alt+2）。
- 防捕获（F7）：共享屏幕/录屏时答案窗从捕获画面消失。

## 热键速查（以 code 版为例，quiz 版差异见文件头注释）

```
Alt+P     截屏识图（同题可续截，自动带多轮记忆）
Alt+1     答案就位后自动打字（再按停止）
Alt+2     剪贴板粘贴整段答案
Alt+3     清空识图记忆（换新题）
F4        隐藏/显示答案窗
F6        Telegram 手机推送开关
F7        防捕获开关
F9        按住解除门控
Ctrl+Esc  紧急暂停     ESC×2 或 Ctrl+Q  退出
```

## 配置

复制 `.env.example` 为 `.env` 并填入：

- `ARK_API_KEY` / `ARK_VISION_MODEL` / `VISION_BASE_URL` — 识图视觉模型（OpenAI 兼容）
- `DEEPSEEK_API_KEY` — 语音问答模型
- `BOT_TOKEN` / `ALLOWED_IDS` / `PROXY` — Telegram 推送
- `ISI_APPKEY` / `ALIYUN_AK_ID` / `ALIYUN_AK_SECRET` / `DASHSCOPE_API_KEY` — 转写/备用 ASR（可选）

`.env` 已在 `.gitignore`，不入库。

## 启动

```bash
python interview-cheat-quiz.py --chameleon   # 测评版
python interview-cheat-code.py --chameleon   # 笔试版
```

或双击对应 `.vbs`（静默启动）。会话日志落 `logs/session-*.jsonl`。

## 依赖

Python 3.12；`pip install pyaudiowpatch websockets requests numpy Pillow`（tkinter 内置）。

启动前先杀旧进程再开新版（同屏双窗会混）。

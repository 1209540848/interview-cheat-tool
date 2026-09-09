# -*- coding: utf-8 -*-
"""typing_code.py — code 版自动输入全家桶（Alt+1 打字 / Alt+2 粘贴 + 净化/变速/再就绪）。

整函数族原样搬入（code 主本）：_after_alt_release 由 engine 热键按下分支以线程调起，
等 Alt 松开才真正执行 type/paste——还按着的 Alt 会把注入字符修饰掉。"""
from .log import log_event              # 事件日志：本模块所有动作都记 JSONL 复盘
from .state import TYPING_STATE         # 打字状态容器（armed/busy/stop/text/pos/start_ts）

def _after_alt_release(fn, *args):
    """Alt+组合触发后不能立刻开打：还按着的 Alt 会把注入字符修饰掉（Alt+A 全选之类）。
    后台线程：等 Alt 松开（最长 2s）再执行 fn(*args)，留 0.1s 手指离键余量"""
    import time as _t                   # 局部导入 time：仅本函数用，不占模块命名空间
    import ctypes as _c                 # 局部导入 ctypes：读系统按键状态需 Win32 API
    t0 = _t.time()                      # 记录开始等待 Alt 松开的时刻（供 2s 超时判断）
    while _t.time() - t0 < 2.0:         # 最多等 2 秒：用户一直按着 Alt 也有兜底
        if not (_c.windll.user32.GetAsyncKeyState(0x12) & 0x8000):
            break                       # 0x12=VK_ALT，最高位=按下状态；已松开 → 跳出
        _t.sleep(0.05)                  # 还没松开 → 睡 50ms 再查（轮询不空转 CPU）
    _t.sleep(0.1)                       # 松开后再留 0.1s 余量，确保手指完全离开 Alt
    try:
        fn(*args)                       # 执行真正的动作：type_answer 或 paste_answer
    except Exception:
        pass                            # 注入异常静默吞掉，不炸掉调用它的线程

def _type_prep(text):
    """打字/粘贴前的答案净化（clippy 用 syntax_tree 解析 markdown 的精简版）：
    带 ``` 代码块 → 只取最后一段代码块本体（笔试目标是代码编辑器，思路文字/围栏
    打进去全是事故）；无代码块（简答/聊天框）→ 去围栏行、剥 ** 与反引号，正文保留"""
    if not text:                        # 空文本直接返回空串
        return ""
    if text.startswith("（") and "）" in text[:40]:      # 剥「（整图没答出…）」类括注前缀
        text = text.split("）", 1)[1].lstrip("\n")       # 取第一个右括号之后的内容
    text = text.strip()                 # 去掉首尾空白
    if not text:                        # 剥完前缀后可能变空
        return ""
    lines = text.splitlines()           # 按行拆开，用于找代码围栏 ``` 
    fences = [i for i, ln in enumerate(lines) if ln.lstrip().startswith("```")]   # 所有围栏行号
    if len(fences) >= 2:                                # 有围栏：取最后一段代码块内容
        body = "\n".join(lines[fences[-2] + 1:fences[-1]]).strip()   # 倒数第二道围栏后 ~ 最后一道围栏前
        if body:                        # 代码块本体非空才用（防止围栏里没内容）
            return body
    out = []                            # 无代码块分支：逐行剥轻量 markdown
    for ln in lines:                                    # 无代码块：正文剥轻量 markdown
        if ln.lstrip().startswith("```"):               # 单独的围栏行（不完整代码块）
            continue                    # 丢掉围栏行本身
        out.append(ln.replace("**", "").replace("`", ""))   # 剥加粗星号与行内反引号
    return "\n".join(out).strip()       # 重拼并去首尾空白

def _type_keystroke_delay(ch, prev, pos):
    """单键间隔（clippy input.rs 延迟特征的收窄版——笔试有时间压力，全照搬 200-400ms 太慢）：
    同字符 20-50ms、空格 10-30、中文 50-100、大写 60-110、数字 45-85、代码常规字符 40-80、
    换行 250-800（翻行要想一下）；前 12 字符 90-150ms 起手慢热，让用户确认在打字"""
    import random as _r                 # 局部导入 random：每个键的延迟是随机区间
    if ch == "\n":                      # 换行最慢：模拟"敲回车前要想一下换行后怎么写"
        return _r.uniform(0.8, 1)
    if ch in (" ", "\t"):               # 空格/制表符最快：手感自然
        return _r.uniform(0.1, 0.3)
    if ch == prev:                      # 与上一字符相同：怕连击，慢一点
        return _r.uniform(0.1, 0.3)
    if pos < 12:                        # 前 12 个字符慢热：给用户确认"开始打字了"
        return _r.uniform(0.1, 0.3)
    o = ord(ch)                         # 取字符码点，按字符类型分档
    if 0x4E00 <= o <= 0x9FFF:                           # CJK 基本区
        return _r.uniform(0.3, 0.6)    # 中文输入法显示慢，给中等间隔
    if ch.isupper():                    # 大写字母：需按 Shift，间隔略大
        return _r.uniform(0.3, 0.6)
    if ch.isdigit():                    # 数字：键盘顶部一行，稍慢
        return _r.uniform(0.3, 0.6)
    if ch.isascii():                    # 代码符号/英文/标点统一档（覆盖绝大多数字符）
        return _r.uniform(0.05, 0.2)                   # 代码符号/英文/标点统一档
    return _r.uniform(0.3, 0.6)                        # 其他（中文标点等）

def type_answer_into_foreground(text):
    """模拟真人键盘把答案逐字打进当前前台窗口的焦点输入框（Alt+1 触发，再按 Alt+1 停止）。
    clippy 式打法：开打前 1.2s 缓冲（clippy 睡 1s 同款）；换行走真实回车；按字符类型
    变速——比旧版全速 30-90ms 注入慢 40% 但更像人手，浏览器/编辑器不易丢字符。
    全字符走 KEYEVENTF_UNICODE 注入（wVk=0）：中英文/符号通用、免 shift 状态，
    也不产生真实 VK——不会被自家 GetAsyncKeyState 轮询误触发。
    目标窗口 title 变化（弹窗/切走）立即停。手动停/焦点停后自动重新就绪（armed），
    再按 Alt+1 从头重打——旧版停完 armed=False 死锁：想重打没入口"""
    import ctypes as _c                 # 局部导入 ctypes：SendInput 注入按键
    import random as _r                 # 局部导入 random：变速 + 偶发长停
    import time as _t                   # 局部导入 time：打字节奏控制

    def _win_title(hwnd):               # 取窗口标题：监控焦点变化用
        try:
            buf = _c.create_unicode_buffer(256)         # 分配 256 字符宽缓冲区接标题
            _c.windll.user32.GetWindowTextW(hwnd, buf, 256)   # Win32 读窗口标题
            return buf.value or "?"     # 空标题兜底显示 "?"
        except Exception:
            return "?"                  # API 失败兜底

    TYPING_STATE["busy"] = True         # 标记打字进行中（热键分支据此判断"正在打"）
    TYPING_STATE["stop"] = False        # 清零停止标记
    TYPING_STATE["start_ts"] = _t.time()   # 记录启动时刻：1 秒内再按 Alt+1 忽略防误停
    try:
        mode = "code" if "```" in text else "text"      # 按文本是否含代码块标记分档（日志用）
        text = _type_prep(text)         # 净化：只留代码块本体或剥轻量 markdown
        if not text:
            log_event({"type": "typing_error", "err": "净化后无内容可打"})
            _rearm("净化后为空")         # 无内容也要回到待打状态（防止 armed 假死）
            return
        class _KBD(_c.Structure):       # Win32 INPUT 结构体的键盘成员（wVk=虚拟键/wScan=扫描码）
            _fields_ = [("wVk", _c.c_ushort), ("wScan", _c.c_ushort),
                        ("dwFlags", _c.c_uint), ("time", _c.c_uint),
                        ("dwExtraInfo", _c.c_size_t)]
        # 血泪教训(2026-09-06):union 必须含 MOUSE/HARD 成员,否则 sizeof(_INPUT)=32
        # < 系统要求 40, SendInput 返回 0 + error 87, 注入全部静默失败
        class _MOUSE(_c.Structure):     # union 的鼠标成员：结构体尺寸对齐必需（见血泪教训注释）
            _fields_ = [("dx", _c.c_long), ("dy", _c.c_long),
                        ("mouseData", _c.c_uint), ("dwFlags", _c.c_uint),
                        ("time", _c.c_uint), ("dwExtraInfo", _c.c_size_t)]
        class _HARD(_c.Structure):      # union 的硬件消息成员：同样是尺寸对齐必需
            _fields_ = [("uMsg", _c.c_uint), ("wParamL", _c.c_ushort),
                        ("wParamH", _c.c_ushort), ("dwExtraInfo", _c.c_size_t)]
        class _UNION(_c.Union):         # 联合体：一次只解释一种输入类型
            _fields_ = [("mi", _MOUSE), ("kbd", _KBD), ("hi", _HARD)]
        class _INPUT(_c.Structure):     # 完整 INPUT 结构：type=输入类型，u=对应联合体
            _fields_ = [("type", _c.c_uint), ("u", _UNION)]
        _user32 = _c.windll.user32      # 缓存 user32 模块引用（避免反复查 DLL）
        _sendinput = _user32.SendInput  # 取 SendInput 函数对象
        _sendinput.argtypes = [_c.c_uint, _c.POINTER(_INPUT), _c.c_int]   # 声明参数类型（64 位必需）
        _sendinput.restype = _c.c_uint  # 返回注入成功个数

        def _key(vk, scan, flags):      # 注入单个按键（按下或抬起由 flags 决定）
            x = _INPUT()                # 构造一个 INPUT 结构体
            x.type = 1                                  # INPUT_KEYBOARD=1
            x.u.kbd.wVk, x.u.kbd.wScan = vk, scan       # 虚拟键码 + 扫描码
            x.u.kbd.dwFlags, x.u.kbd.time = flags, 0    # 标志位（UNICODE/按下/抬起）+ 时间戳 0
            x.u.kbd.dwExtraInfo = 0     # 附加信息置 0
            n = _sendinput(1, _c.byref(x), _c.sizeof(_INPUT))   # 发送 1 个输入事件
            if not n:                                   # 注入被拒:只记前 3 次防刷屏
                TYPING_STATE["fail_cnt"] = TYPING_STATE.get("fail_cnt", 0) + 1   # 累计失败次数
                if TYPING_STATE["fail_cnt"] <= 3:       # 只记前 3 次，防止日志刷屏
                    log_event({"type": "key_inject_fail", "err": _c.get_last_error()})

        def _char(ch):                  # 注入单个可见字符（走 UNICODE 通道）
            _key(0, ord(ch), 0x0004)                    # KEYEVENTF_UNICODE 按下
            _key(0, ord(ch), 0x0004 | 0x0002)           # + KEYEVENTF_KEYUP 抬起

        target = _user32.GetForegroundWindow()          # 锁定的目标窗（用户按 Alt+1 时点好的答题页）
        title0 = _win_title(target)     # 记下目标窗口标题（焦点漂移判定基准）
        log_event({"type": "typing_start", "hwnd": target, "title": title0,
                   "chars": len(text), "mode": mode})   # 记录本次打字起点
        _t.sleep(1.2)                                   # 开打前缓冲：页面/焦点稳定，用户有零点几秒确认
        # [2026-09-08 自动缩进适配] 在线笔试 IDE（monaco/牛客等）回车后自动补缩进，行首空白再
        # 原样注入会双缩进 → 开启时跳过答案行首空白、层级交给编辑器自动缩进；首次非空白才恢复逐字。
        # 记事本等无自动缩进的场景用 run_code.py --no-auto-indent 关闭（缩进原样注入，回到旧行为）
        _auto_indent = TYPING_STATE.get("auto_indent", True)   # 模式开关（run_code --no-auto-indent 关闭）
        _line_start = True                      # 当前处于行首（文本开头/每次回车后）：行首空白跳过
        i = 0                                           # 每次触发都从头打(简单可靠)
        prev = None                     # 上一字符（用于同字符变速）
        while i < len(text):            # 逐字符注入，直到打完全部文本
            # [2026-09-08 暂停/继续升级] 原「再按 Alt+1 = 停止」整段保留供回溯：
            #     if TYPING_STATE["stop"]:
            #         log_event({"type": "typing_stop", "chars": i})
            #         print(f"⏹ 已停止自动输入（再按 Alt+1 从头重打,已打 {i}/{len(text)}）", flush=True)
            #         _rearm("手动停止")
            #         return
            if TYPING_STATE["stop"] and not TYPING_STATE["paused"]:   # 打字中按 Alt+1 → 暂停（复用 engine 的 stop 信号，engine 零改动）
                TYPING_STATE["stop"] = False        # 消费暂停信号（否则下轮循环误判）
                TYPING_STATE["paused"] = True       # 置暂停态（busy 保持 True，热键分支继续认 busy）
                TYPING_STATE["pos"] = i             # 记断点：已打字符数（续打走局部 i，pos 供状态/日志）
                print(f"⏸ 已暂停（再按 Alt+1 继续；已打 {i}/{len(text)}）", flush=True)
                log_event({"type": "typing_paused", "chars": i})
                while TYPING_STATE["paused"]:       # 暂停等待：只等 Alt+1 信号（暂停期间允许切走看题）
                    _t.sleep(0.05)                  # 50ms 轮询信号（不占 CPU）
                    if TYPING_STATE["stop"]:        # 暂停中按 Alt+1 → 判定继续 or 停止
                        TYPING_STATE["stop"] = False    # 消费信号（防止恢复后主循环再次暂停）
                        cur = _user32.GetForegroundWindow()   # 看当前焦点在哪
                        if cur == target or _win_title(cur) == title0:   # 焦点还在答题框 → 继续
                            TYPING_STATE["paused"] = False
                            print(f"▶️ 继续输入（从第 {i} 字符续打）", flush=True)
                            log_event({"type": "typing_resume", "chars": i})
                            break
                        # 焦点已切走：按 Alt+1 = 停止（保留旧「停止+重打」入口，防续打打进别的窗口）
                        log_event({"type": "typing_stop", "chars": i})
                        print(f"⏹ 已停止（焦点已切走；点回答题框再按 Alt+1 从头重打,已打 {i}/{len(text)}）", flush=True)
                        TYPING_STATE["paused"] = False  # 清暂停态（线程即将 return）
                        _rearm("手动停止")               # 回到待打状态，可重打
                        return
                continue                            # 恢复后回主循环：从断点 i 接着打
            cur = _user32.GetForegroundWindow()         # 当前前台窗口
            if cur != target and _win_title(cur) != title0:
                # 焦点跑到别的窗口：停。同窗口内顶层 hwnd 漂移（Chromium 内部激活变化）
                # title 不变则不算丢焦点，继续打
                log_event({"type": "typing_abort_focus", "chars": i, "hwnd": target,
                           "title": title0, "cur_hwnd": cur,
                           "cur_title": _win_title(cur)})   # 记录焦点丢失现场
                print(f"⚠️ 焦点变了，自动输入已停（再按 Alt+1 从头重打,已打 {i}/{len(text)}）", flush=True)
                _rearm("焦点变化")       # 焦点丢了也要重新 armed
                return
            ch = text[i]                # 取当前要打的字符
            if _auto_indent and _line_start:
                # [2026-09-08 自动缩进适配] 行首空白：不注入，快进交给编辑器自动缩进接管
                if ch in " \t":
                    prev = ch           # 同步上一字符（空格变速语义，值无实义）
                    i += 1              # 跳过该空白字符（编辑器已自动补了缩进）
                    continue            # 不睡延迟：交给 IDE 的缩进无需逐格模拟
                _line_start = False     # 首个非空白字符：恢复逐字注入
            if ch == "\n":                              # 回车真实按键（编辑器才认段落）
                _key(0x0D, 0, 0)        # VK_RETURN 按下
                _key(0x0D, 0, 2)        # VK_RETURN 抬起（flags=KEYEVENTF_KEYUP）
                _line_start = True      # [2026-09-08 自动缩进适配] 回车后进入行首：下一行行首空白跳过
            elif ch == "\t":            # 制表符：编辑器里常被吃掉，用 4 空格替代
                for _ in range(4):      # 打 4 个空格
                    _char(" ")
            elif ch != "\r":            # 跳过 \r（Windows 换行里的回车残渣）
                _char(ch)               # 其余字符走 UNICODE 注入
            i += 1                      # 已打字符数 +1
            _t.sleep(_type_keystroke_delay(ch, prev, i))   # 按字符类型睡对应间隔
            prev = ch                   # 记录当前字符供下轮同字符变速
            if _r.random() < 0.07:                      # 偶发「想一下」长停
                _t.sleep(_r.uniform(0.15, 0.5))         # 7% 概率随机停 0.15-0.5s（更像真人）
            if i % 140 == 0:                            # 长代码偶尔歇口气
                _t.sleep(_r.uniform(0.4, 0.9))          # 每 140 字符喘一次（防被平台判机器）
        print(f"⌨️ 自动输入完成（{i} 字符）", flush=True)
        log_event({"type": "typing_done", "chars": i, "mode": mode})
        _rearm("完成")      # 答案未消费:同一 text 可再按 Alt+1 从头重打(用户:按一次下一次不行)
    except Exception as e:              # 任何异常统一走日志 + 重新 armed
        log_event({"type": "typing_error",
                   "err": f"{type(e).__name__}: {e}"[:300]})
        _rearm("异常")                   # 崩完不吞答案：可再按 Alt+1 重试
    finally:
        TYPING_STATE["busy"] = False    # 无论成败，busy 必须清掉（否则热键卡死）

def _rearm(why):
    """打完/停/崩的公共出口：回到「待打」状态——text 还在，再按 Alt+1/Alt+2 可重打重贴。
    提升为模块级(2026-09-06):原来嵌在 type_answer 里,paste 函数调它 NameError,
    粘贴成功后 armed 永远 false → 用户反馈「只能按一次」"""
    TYPING_STATE["armed"] = True        # 重新就绪：答案还在，可再次注入
    log_event({"type": "typing_rearmed", "why": why})   # 记录就绪原因（复盘"为什么能再打"）

def paste_answer_into_foreground():
    """Alt+2：剪贴板粘贴净化后的答案（clippy 同款 paste_text 通道，Ctrl+V 组合）。
    打字链路打不进去（编辑器吞字符/焦点玄学）时一键兜底——浏览器对粘贴零抵抗力。
    完成即消耗 armed；同样只在有答案待打时劫持 Alt+2"""
    import ctypes as _c                 # 局部导入 ctypes：剪贴板 + SendInput 组合键
    import time as _t                   # 局部导入 time：写入剪贴板与按键之间的缓冲
    text = _type_prep(TYPING_STATE["text"] or "")   # 取待打答案并净化（与打字共用逻辑）
    if not text:                        # 净化后为空：无事可贴直接返回
        return
    TYPING_STATE["busy"] = True         # 标记粘贴进行中（防止与打字并发）
    TYPING_STATE["stop"] = False        # 清零停止标记
    TYPING_STATE["start_ts"] = _t.time()   # 记录启动时刻（语义与打字一致）
    log_event({"type": "paste_start", "chars": len(text),
               "mode": "code" if "```" in TYPING_STATE["text"] else "text"})
    try:
        # 1) 剪贴板写入 CF_UNICODETEXT
        _u32, _k32 = _c.windll.user32, _c.windll.kernel32   # 两个 DLL 的函数都在本步用
        # 血泪教训(2026-09-06):所有收 handle 的 API 都必须设 argtypes → 64 位
        # handle 缺省被当 32 位 int: GlobalAlloc/GlobalLock/SetClipboardData 静默
        # 写坏(空剪贴板), GlobalUnlock 直接抛 OverflowError 崩掉整个粘贴
        _k32.GlobalAlloc.restype = _c.c_size_t      # 返回 HGLOBAL：64 位必须声明 c_size_t
        _k32.GlobalAlloc.argtypes = [_c.c_uint, _c.c_size_t]    # (uFlags, dwBytes)
        _k32.GlobalLock.restype = _c.c_void_p       # 返回内存指针
        _k32.GlobalLock.argtypes = [_c.c_size_t]    # 参数是 HGLOBAL
        _k32.GlobalUnlock.restype = _c.c_int        # 解锁句柄
        _k32.GlobalUnlock.argtypes = [_c.c_size_t]
        _u32.OpenClipboard.argtypes = [_c.c_size_t] # 打开剪贴板（参数是窗口句柄）
        _u32.OpenClipboard.restype = _c.c_bool
        _u32.EmptyClipboard.restype = _c.c_bool     # 清空剪贴板
        _u32.SetClipboardData.restype = _c.c_size_t # 写入数据
        _u32.SetClipboardData.argtypes = [_c.c_uint, _c.c_size_t]   # (格式, 句柄)
        _u32.CloseClipboard.restype = _c.c_bool     # 关闭剪贴板
        clip_ok = False                 # 剪贴板写入成功标记（日志用）
        if _u32.OpenClipboard(0):       # 打开系统剪贴板（0=不关联窗口）
            try:
                _u32.EmptyClipboard()   # 先清空，避免旧内容残留
                blob = text.encode("utf-16-le") + b"\x00\x00"   # UTF-16LE + 双字节结尾（CF_UNICODETEXT 要求）
                h = _k32.GlobalAlloc(0x0042, len(blob))     # GMEM_MOVEABLE|GMEM_ZEROINIT
                if h:                   # 分配成功才继续
                    p = _k32.GlobalLock(h)      # 锁定内存块拿指针
                    if p:                       # 锁定成功
                        _c.memmove(p, blob, len(blob))      # 把文本拷进全局内存
                        _k32.GlobalUnlock(h)    # 解锁（释放写锁）
                    clip_ok = bool(_u32.SetClipboardData(13, h))   # CF_UNICODETEXT=13；接管句柄
            finally:
                _u32.CloseClipboard()   # 无论成败都关闭剪贴板
        log_event({"type": "paste_clip", "ok": clip_ok, "chars": len(text)})
        # 2) 缓冲后模拟 Ctrl+V（真实 VK 组合键）
        _t.sleep(1.0)                   # 等 1s：剪贴板稳定 + 用户来得及把焦点放对
        class _KBD(_c.Structure):       # 键盘成员结构体（同打字函数，尺寸对齐见血泪教训）
            _fields_ = [("wVk", _c.c_ushort), ("wScan", _c.c_ushort),
                        ("dwFlags", _c.c_uint), ("time", _c.c_uint),
                        ("dwExtraInfo", _c.c_size_t)]
        # 血泪教训(2026-09-06):union 必须含 MOUSE/HARD 成员,否则 sizeof(_INPUT)=32
        # < 系统要求 40, SendInput 返回 0 + error 87, 注入全部静默失败
        class _MOUSE(_c.Structure):     # 鼠标成员：尺寸对齐必需
            _fields_ = [("dx", _c.c_long), ("dy", _c.c_long),
                        ("mouseData", _c.c_uint), ("dwFlags", _c.c_uint),
                        ("time", _c.c_uint), ("dwExtraInfo", _c.c_size_t)]
        class _HARD(_c.Structure):      # 硬件消息成员：尺寸对齐必需
            _fields_ = [("uMsg", _c.c_uint), ("wParamL", _c.c_ushort),
                        ("wParamH", _c.c_ushort), ("dwExtraInfo", _c.c_size_t)]
        class _UNION(_c.Union):         # 联合体：三种输入类型复用同一块内存
            _fields_ = [("mi", _MOUSE), ("kbd", _KBD), ("hi", _HARD)]
        class _INPUT(_c.Structure):     # 完整 INPUT 结构
            _fields_ = [("type", _c.c_uint), ("u", _UNION)]
        _sendinput = _u32.SendInput     # 取 SendInput
        _sendinput.argtypes = [_c.c_uint, _c.POINTER(_INPUT), _c.c_int]
        _sendinput.restype = _c.c_uint
        def _key(vk, flags):            # 注入真实虚拟键（Ctrl+V 是真实 VK，不能走 UNICODE）
            x = _INPUT()                # 构造 INPUT
            x.type = 1                  # INPUT_KEYBOARD
            x.u.kbd.wVk, x.u.kbd.wScan, x.u.kbd.dwFlags = vk, 0, flags   # 虚拟键 + 标志
            x.u.kbd.dwExtraInfo = 0     # 附加信息 0
            n = _sendinput(1, _c.byref(x), _c.sizeof(_INPUT))   # 发送
            if not n:                                   # 注入被拒:只记前 3 次防刷屏
                TYPING_STATE["fail_cnt"] = TYPING_STATE.get("fail_cnt", 0) + 1
                if TYPING_STATE["fail_cnt"] <= 3:
                    log_event({"type": "key_inject_fail", "err": _c.get_last_error()})
        for seq in ((0x11, 0), (0x56, 0), (0x56, 2), (0x11, 2)):   # Ctrl down→V down→V up→Ctrl up
            _key(*seq)                  # 依次发送 4 个按键事件（顺序不能乱）
            _t.sleep(0.05)              # 每个按键之间隔 50ms（太快会被目标程序忽略）
        log_event({"type": "paste_done", "chars": len(text), "clip_ok": clip_ok})
        _rearm("完成")      # 同 typing:粘贴完答案仍在,可再按 Alt+2 重贴
        print("📋 已粘贴", flush=True)
    except Exception as e:              # 任何异常统一走日志 + 重新 armed
        log_event({"type": "paste_error", "err": f"{type(e).__name__}: {e}"[:300]})
        _rearm("异常")      # 崩完不吞答案:可再按 Alt+2 重试(否则 armed 永久 false 变哑巴)
    finally:
        TYPING_STATE["busy"] = False    # 无论成败清 busy（防止热键分支卡死）

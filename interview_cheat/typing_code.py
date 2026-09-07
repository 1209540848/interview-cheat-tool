# -*- coding: utf-8 -*-
"""typing_code.py — code 版自动输入全家桶（Alt+1 打字 / Alt+2 粘贴 + 净化/变速/再就绪）。

整函数族原样搬入（code 主本）：_after_alt_release 由 engine 热键按下分支以线程调起，
等 Alt 松开才真正执行 type/paste——还按着的 Alt 会把注入字符修饰掉。"""
from .log import log_event
from .state import TYPING_STATE

def _after_alt_release(fn, *args):
    """Alt+组合触发后不能立刻开打：还按着的 Alt 会把注入字符修饰掉（Alt+A 全选之类）。
    后台线程：等 Alt 松开（最长 2s）再执行 fn(*args)，留 0.1s 手指离键余量"""
    import time as _t
    import ctypes as _c
    t0 = _t.time()
    while _t.time() - t0 < 2.0:
        if not (_c.windll.user32.GetAsyncKeyState(0x12) & 0x8000):
            break
        _t.sleep(0.05)
    _t.sleep(0.1)
    try:
        fn(*args)
    except Exception:
        pass

def _type_prep(text):
    """打字/粘贴前的答案净化（clippy 用 syntax_tree 解析 markdown 的精简版）：
    带 ``` 代码块 → 只取最后一段代码块本体（笔试目标是代码编辑器，思路文字/围栏
    打进去全是事故）；无代码块（简答/聊天框）→ 去围栏行、剥 ** 与反引号，正文保留"""
    if not text:
        return ""
    if text.startswith("（") and "）" in text[:40]:      # 剥「（整图没答出…）」类括注前缀
        text = text.split("）", 1)[1].lstrip("\n")
    text = text.strip()
    if not text:
        return ""
    lines = text.splitlines()
    fences = [i for i, ln in enumerate(lines) if ln.lstrip().startswith("```")]
    if len(fences) >= 2:                                # 有围栏：取最后一段代码块内容
        body = "\n".join(lines[fences[-2] + 1:fences[-1]]).strip()
        if body:
            return body
    out = []
    for ln in lines:                                    # 无代码块：正文剥轻量 markdown
        if ln.lstrip().startswith("```"):
            continue
        out.append(ln.replace("**", "").replace("`", ""))
    return "\n".join(out).strip()

def _type_keystroke_delay(ch, prev, pos):
    """单键间隔（clippy input.rs 延迟特征的收窄版——笔试有时间压力，全照搬 200-400ms 太慢）：
    同字符 20-50ms、空格 10-30、中文 50-100、大写 60-110、数字 45-85、代码常规字符 40-80、
    换行 250-800（翻行要想一下）；前 12 字符 90-150ms 起手慢热，让用户确认在打字"""
    import random as _r
    if ch == "\n":
        return _r.uniform(0.25, 0.8)
    if ch in (" ", "\t"):
        return _r.uniform(0.01, 0.03)
    if ch == prev:
        return _r.uniform(0.02, 0.05)
    if pos < 12:
        return _r.uniform(0.09, 0.15)
    o = ord(ch)
    if 0x4E00 <= o <= 0x9FFF:                           # CJK 基本区
        return _r.uniform(0.05, 0.1)
    if ch.isupper():
        return _r.uniform(0.06, 0.11)
    if ch.isdigit():
        return _r.uniform(0.045, 0.085)
    if ch.isascii():
        return _r.uniform(0.04, 0.08)                   # 代码符号/英文/标点统一档
    return _r.uniform(0.05, 0.1)                        # 其他（中文标点等）

def type_answer_into_foreground(text):
    """模拟真人键盘把答案逐字打进当前前台窗口的焦点输入框（Alt+1 触发，再按 Alt+1 停止）。
    clippy 式打法：开打前 1.2s 缓冲（clippy 睡 1s 同款）；换行走真实回车；按字符类型
    变速——比旧版全速 30-90ms 注入慢 40% 但更像人手，浏览器/编辑器不易丢字符。
    全字符走 KEYEVENTF_UNICODE 注入（wVk=0）：中英文/符号通用、免 shift 状态，
    也不产生真实 VK——不会被自家 GetAsyncKeyState 轮询误触发。
    目标窗口 title 变化（弹窗/切走）立即停。手动停/焦点停后自动重新就绪（armed），
    再按 Alt+1 从头重打——旧版停完 armed=False 死锁：想重打没入口"""
    import ctypes as _c
    import random as _r
    import time as _t

    def _win_title(hwnd):
        try:
            buf = _c.create_unicode_buffer(256)
            _c.windll.user32.GetWindowTextW(hwnd, buf, 256)
            return buf.value or "?"
        except Exception:
            return "?"

    TYPING_STATE["busy"] = True
    TYPING_STATE["stop"] = False
    TYPING_STATE["start_ts"] = _t.time()
    try:
        mode = "code" if "```" in text else "text"
        text = _type_prep(text)
        if not text:
            log_event({"type": "typing_error", "err": "净化后无内容可打"})
            _rearm("净化后为空")
            return
        class _KBD(_c.Structure):
            _fields_ = [("wVk", _c.c_ushort), ("wScan", _c.c_ushort),
                        ("dwFlags", _c.c_uint), ("time", _c.c_uint),
                        ("dwExtraInfo", _c.c_size_t)]
        # 血泪教训(2026-09-06):union 必须含 MOUSE/HARD 成员,否则 sizeof(_INPUT)=32
        # < 系统要求 40, SendInput 返回 0 + error 87, 注入全部静默失败
        class _MOUSE(_c.Structure):
            _fields_ = [("dx", _c.c_long), ("dy", _c.c_long),
                        ("mouseData", _c.c_uint), ("dwFlags", _c.c_uint),
                        ("time", _c.c_uint), ("dwExtraInfo", _c.c_size_t)]
        class _HARD(_c.Structure):
            _fields_ = [("uMsg", _c.c_uint), ("wParamL", _c.c_ushort),
                        ("wParamH", _c.c_ushort), ("dwExtraInfo", _c.c_size_t)]
        class _UNION(_c.Union):
            _fields_ = [("mi", _MOUSE), ("kbd", _KBD), ("hi", _HARD)]
        class _INPUT(_c.Structure):
            _fields_ = [("type", _c.c_uint), ("u", _UNION)]
        _user32 = _c.windll.user32
        _sendinput = _user32.SendInput
        _sendinput.argtypes = [_c.c_uint, _c.POINTER(_INPUT), _c.c_int]
        _sendinput.restype = _c.c_uint

        def _key(vk, scan, flags):
            x = _INPUT()
            x.type = 1                                  # INPUT_KEYBOARD
            x.u.kbd.wVk, x.u.kbd.wScan = vk, scan
            x.u.kbd.dwFlags, x.u.kbd.time = flags, 0
            x.u.kbd.dwExtraInfo = 0
            n = _sendinput(1, _c.byref(x), _c.sizeof(_INPUT))
            if not n:                                   # 注入被拒:只记前 3 次防刷屏
                TYPING_STATE["fail_cnt"] = TYPING_STATE.get("fail_cnt", 0) + 1
                if TYPING_STATE["fail_cnt"] <= 3:
                    log_event({"type": "key_inject_fail", "err": _c.get_last_error()})

        def _char(ch):
            _key(0, ord(ch), 0x0004)                    # KEYEVENTF_UNICODE 按下
            _key(0, ord(ch), 0x0004 | 0x0002)           # + KEYEVENTF_KEYUP 抬起

        target = _user32.GetForegroundWindow()          # 锁定的目标窗（用户按 Alt+1 时点好的答题页）
        title0 = _win_title(target)
        log_event({"type": "typing_start", "hwnd": target, "title": title0,
                   "chars": len(text), "mode": mode})
        _t.sleep(1.2)                                   # 开打前缓冲：页面/焦点稳定，用户有零点几秒确认
        i = 0                                           # 每次触发都从头打(简单可靠)
        prev = None
        while i < len(text):
            if TYPING_STATE["stop"]:
                log_event({"type": "typing_stop", "chars": i})
                print(f"⏹ 已停止自动输入（再按 Alt+1 从头重打,已打 {i}/{len(text)}）", flush=True)
                _rearm("手动停止")
                return
            cur = _user32.GetForegroundWindow()
            if cur != target and _win_title(cur) != title0:
                # 焦点跑到别的窗口：停。同窗口内顶层 hwnd 漂移（Chromium 内部激活变化）
                # title 不变则不算丢焦点，继续打
                log_event({"type": "typing_abort_focus", "chars": i, "hwnd": target,
                           "title": title0, "cur_hwnd": cur,
                           "cur_title": _win_title(cur)})
                print(f"⚠️ 焦点变了，自动输入已停（再按 Alt+1 从头重打,已打 {i}/{len(text)}）", flush=True)
                _rearm("焦点变化")
                return
            ch = text[i]
            if ch == "\n":                              # 回车真实按键（编辑器才认段落）
                _key(0x0D, 0, 0)
                _key(0x0D, 0, 2)
            elif ch == "\t":
                for _ in range(4):
                    _char(" ")
            elif ch != "\r":
                _char(ch)
            i += 1
            _t.sleep(_type_keystroke_delay(ch, prev, i))
            prev = ch
            if _r.random() < 0.07:                      # 偶发「想一下」长停
                _t.sleep(_r.uniform(0.15, 0.5))
            if i % 140 == 0:                            # 长代码偶尔歇口气
                _t.sleep(_r.uniform(0.4, 0.9))
        print(f"⌨️ 自动输入完成（{i} 字符）", flush=True)
        log_event({"type": "typing_done", "chars": i, "mode": mode})
        _rearm("完成")      # 答案未消费:同一 text 可再按 Alt+1 从头重打(用户:按一次下一次不行)
    except Exception as e:
        log_event({"type": "typing_error",
                   "err": f"{type(e).__name__}: {e}"[:300]})
        _rearm("异常")
    finally:
        TYPING_STATE["busy"] = False

def _rearm(why):
    """打完/停/崩的公共出口：回到「待打」状态——text 还在，再按 Alt+1/Alt+2 可重打重贴。
    提升为模块级(2026-09-06):原来嵌在 type_answer 里,paste 函数调它 NameError,
    粘贴成功后 armed 永远 false → 用户反馈「只能按一次」"""
    TYPING_STATE["armed"] = True
    log_event({"type": "typing_rearmed", "why": why})

def paste_answer_into_foreground():
    """Alt+2：剪贴板粘贴净化后的答案（clippy 同款 paste_text 通道，Ctrl+V 组合）。
    打字链路打不进去（编辑器吞字符/焦点玄学）时一键兜底——浏览器对粘贴零抵抗力。
    完成即消耗 armed；同样只在有答案待打时劫持 Alt+2"""
    import ctypes as _c
    import time as _t
    text = _type_prep(TYPING_STATE["text"] or "")
    if not text:
        return
    TYPING_STATE["busy"] = True
    TYPING_STATE["stop"] = False
    TYPING_STATE["start_ts"] = _t.time()
    log_event({"type": "paste_start", "chars": len(text),
               "mode": "code" if "```" in TYPING_STATE["text"] else "text"})
    try:
        # 1) 剪贴板写入 CF_UNICODETEXT
        _u32, _k32 = _c.windll.user32, _c.windll.kernel32
        # 血泪教训(2026-09-06):所有收 handle 的 API 都必须设 argtypes → 64 位
        # handle 缺省被当 32 位 int: GlobalAlloc/GlobalLock/SetClipboardData 静默
        # 写坏(空剪贴板), GlobalUnlock 直接抛 OverflowError 崩掉整个粘贴
        _k32.GlobalAlloc.restype = _c.c_size_t
        _k32.GlobalAlloc.argtypes = [_c.c_uint, _c.c_size_t]
        _k32.GlobalLock.restype = _c.c_void_p
        _k32.GlobalLock.argtypes = [_c.c_size_t]
        _k32.GlobalUnlock.restype = _c.c_int
        _k32.GlobalUnlock.argtypes = [_c.c_size_t]
        _u32.OpenClipboard.argtypes = [_c.c_size_t]
        _u32.OpenClipboard.restype = _c.c_bool
        _u32.EmptyClipboard.restype = _c.c_bool
        _u32.SetClipboardData.restype = _c.c_size_t
        _u32.SetClipboardData.argtypes = [_c.c_uint, _c.c_size_t]
        _u32.CloseClipboard.restype = _c.c_bool
        clip_ok = False
        if _u32.OpenClipboard(0):
            try:
                _u32.EmptyClipboard()
                blob = text.encode("utf-16-le") + b"\x00\x00"
                h = _k32.GlobalAlloc(0x0042, len(blob))     # GMEM_MOVEABLE|GMEM_ZEROINIT
                if h:
                    p = _k32.GlobalLock(h)
                    if p:
                        _c.memmove(p, blob, len(blob))
                        _k32.GlobalUnlock(h)
                    clip_ok = bool(_u32.SetClipboardData(13, h))   # CF_UNICODETEXT
            finally:
                _u32.CloseClipboard()
        log_event({"type": "paste_clip", "ok": clip_ok, "chars": len(text)})
        # 2) 缓冲后模拟 Ctrl+V（真实 VK 组合键）
        _t.sleep(1.0)
        class _KBD(_c.Structure):
            _fields_ = [("wVk", _c.c_ushort), ("wScan", _c.c_ushort),
                        ("dwFlags", _c.c_uint), ("time", _c.c_uint),
                        ("dwExtraInfo", _c.c_size_t)]
        # 血泪教训(2026-09-06):union 必须含 MOUSE/HARD 成员,否则 sizeof(_INPUT)=32
        # < 系统要求 40, SendInput 返回 0 + error 87, 注入全部静默失败
        class _MOUSE(_c.Structure):
            _fields_ = [("dx", _c.c_long), ("dy", _c.c_long),
                        ("mouseData", _c.c_uint), ("dwFlags", _c.c_uint),
                        ("time", _c.c_uint), ("dwExtraInfo", _c.c_size_t)]
        class _HARD(_c.Structure):
            _fields_ = [("uMsg", _c.c_uint), ("wParamL", _c.c_ushort),
                        ("wParamH", _c.c_ushort), ("dwExtraInfo", _c.c_size_t)]
        class _UNION(_c.Union):
            _fields_ = [("mi", _MOUSE), ("kbd", _KBD), ("hi", _HARD)]
        class _INPUT(_c.Structure):
            _fields_ = [("type", _c.c_uint), ("u", _UNION)]
        _sendinput = _u32.SendInput
        _sendinput.argtypes = [_c.c_uint, _c.POINTER(_INPUT), _c.c_int]
        _sendinput.restype = _c.c_uint
        def _key(vk, flags):
            x = _INPUT()
            x.type = 1
            x.u.kbd.wVk, x.u.kbd.wScan, x.u.kbd.dwFlags = vk, 0, flags
            x.u.kbd.dwExtraInfo = 0
            n = _sendinput(1, _c.byref(x), _c.sizeof(_INPUT))
            if not n:                                   # 注入被拒:只记前 3 次防刷屏
                TYPING_STATE["fail_cnt"] = TYPING_STATE.get("fail_cnt", 0) + 1
                if TYPING_STATE["fail_cnt"] <= 3:
                    log_event({"type": "key_inject_fail", "err": _c.get_last_error()})
        for seq in ((0x11, 0), (0x56, 0), (0x56, 2), (0x11, 2)):   # Ctrl down→V down→V up→Ctrl up
            _key(*seq)
            _t.sleep(0.05)
        log_event({"type": "paste_done", "chars": len(text), "clip_ok": clip_ok})
        _rearm("完成")      # 同 typing:粘贴完答案仍在,可再按 Alt+2 重贴
        print("📋 已粘贴", flush=True)
    except Exception as e:
        log_event({"type": "paste_error", "err": f"{type(e).__name__}: {e}"[:300]})
        _rearm("异常")      # 崩完不吞答案:可再按 Alt+2 重试(否则 armed 永久 false 变哑巴)
    finally:
        TYPING_STATE["busy"] = False

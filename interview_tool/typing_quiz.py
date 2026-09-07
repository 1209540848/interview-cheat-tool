# -*- coding: utf-8 -*-
"""typing_quiz.py — quiz 版自动输入（按 1 触发/再按停，简化逻辑整函数原样）。"""
from .log import log_event
from .state import TYPING_STATE

def type_answer_into_foreground(text):
    """模拟真人键盘把答案逐字打进当前前台窗口的焦点输入框（按 1 触发，再按 1 停止）。
    全字符走 KEYEVENTF_UNICODE 注入（wVk=0）：中英文/符号通用、免 shift 状态，
    也不产生真实 VK——不会被自家 GetAsyncKeyState 轮询误触发。
    焦点被抢走（弹窗/点了别处）立即停，防打错地方"""
    import ctypes as _c
    import random as _r
    import time as _t
    TYPING_STATE["busy"] = True
    TYPING_STATE["stop"] = False
    try:
        if text.startswith("（") and "）" in text[:40]:   # 剥「（整图没答出…）」类括注前缀再打
            text = text.split("）", 1)[1].lstrip("\n")
        text = text.strip()
        if not text:
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

        target = _user32.GetForegroundWindow()          # 锁定的目标窗（用户按 1 时点好的答题页）
        i = 0                                           # 每次触发都从头打(简单可靠)
        while i < len(text):
            if TYPING_STATE["stop"]:
                print(f"⏹ 已停止自动输入（再按 1 从头重打,已打 {i}/{len(text)}）", flush=True)
                TYPING_STATE["armed"] = True
                return
            if _user32.GetForegroundWindow() != target:  # 焦点跑了：停，防打到别的窗
                print(f"⚠️ 焦点变了，自动输入已停（再按 1 从头重打,已打 {i}/{len(text)}）", flush=True)
                TYPING_STATE["armed"] = True
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
            _t.sleep(_r.uniform(0.03, 0.09))            # 基准键速：像人快速敲
            if _r.random() < 0.18:                      # 偶发「想一下」长停
                _t.sleep(_r.uniform(0.12, 0.4))
            if i % 150 == 0:                            # 长文/长代码偶尔歇口气
                _t.sleep(_r.uniform(0.5, 1.0))
        print(f"⌨️ 自动输入完成（{i} 字符）", flush=True)
        TYPING_STATE["armed"] = True   # 打完不消耗答案:再按 1 从头重打
    finally:
        TYPING_STATE["busy"] = False

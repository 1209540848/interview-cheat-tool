#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_code.py — code 笔试版薄入口（历史：旧 code 单体 + hidden-start-code.vbs）。

唯一职责：把仓库根塞进 sys.path（vbs 从任意 cwd 启动都能 import interview_tool），
然后 engine.main(profiles.CODE)。全部场景差异（提示词/键位/窗口/ESC 双按退出）由
profiles.CODE 收容，主本零场景判断。

命令行参数与旧单体一致：--api-key/--model/--no-inject/--no-window/--acrylic/
--chameleon/--manual/--loop-tcp PORT（engine.main 的 argparse 定义）。
另增 --no-auto-indent（2026-09-08）：记事本等无自动缩进的编辑器用，本入口剥掉后交 engine。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from interview_tool import engine, profiles

if __name__ == "__main__":
    # [2026-09-08 自动缩进适配] --no-auto-indent：记事本等无自动缩进的编辑器用（在线笔试
    # IDE 默认开：回车后跳过行首空白、层级交给编辑器自动缩进）。在薄入口剥掉该参数再交给
    # engine.main（它的 argparse 不认识此参数，传下去会 unrecognized 报错），转环境变量
    # 给 state.TYPING_STATE["auto_indent"] 兜底判断（state 模块级已读环境变量初始化）。
    _argv = sys.argv[1:]
    if "--no-auto-indent" in _argv:
        os.environ["NO_AUTO_INDENT"] = "1"
        _argv = [a for a in _argv if a != "--no-auto-indent"]
    sys.argv = ["run_code.py"] + _argv
    engine.main(profiles.CODE)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_code.py — code 笔试版薄入口（历史：旧 code 单体 + hidden-start-code.vbs）。

唯一职责：把仓库根塞进 sys.path（vbs 从任意 cwd 启动都能 import interview_tool），
然后 engine.main(profiles.CODE)。全部场景差异（提示词/键位/窗口/ESC 双按退出）由
profiles.CODE 收容，主本零场景判断。

命令行参数与旧单体一致：--api-key/--model/--no-inject/--no-window/--acrylic/
--chameleon/--manual/--loop-tcp PORT（engine.main 的 argparse 定义）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from interview_tool import engine, profiles

if __name__ == "__main__":
    engine.main(profiles.CODE)

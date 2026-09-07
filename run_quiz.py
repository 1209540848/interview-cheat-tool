#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_quiz.py — quiz 测评版薄入口（历史：interview-cheat-quiz.py 单体 + hidden-start-quiz.vbs）。

唯一职责：把仓库根塞进 sys.path（vbs 从任意 cwd 启动都能 import interview_cheat），
然后 engine.main(profiles.QUIZ)。全部场景差异（提示词/键位/窗口/ESC 退出节奏）由
profiles.QUIZ 收容，主本零场景判断。

命令行参数与旧单体一致：--api-key/--model/--no-inject/--no-window/--acrylic/
--chameleon/--manual/--loop-tcp PORT（engine.main 的 argparse 定义）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from interview_cheat import engine, profiles

if __name__ == "__main__":
    engine.main(profiles.QUIZ)

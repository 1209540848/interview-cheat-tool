#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""assemble.py — 单体切片装配器（行为等价重构的机械部分）。

为什么存在：重构要求函数/常量"逐字节搬移"。手工抄 2600 行必有转录错，
本工具直接从磁盘源码按 AST 顶层符号闭区间切片，拼进目标模块——
切片永远等于源码，装配器不改写、不转写任何函数体。

用法:
  python tools/assemble.py tools/specs/<step>.json     # 按 spec 装配/覆盖模块
  python tools/assemble.py --symbols <源.py>            # 列出顶层符号名（写 spec 用）
  python tools/assemble.py --census <模块.py>           # 报告"用了但没定义/没导入"的全局名

spec JSON: {"builds": [{"source": "interview-cheat-code.py",   # 切片来源
                        "out": "interview_cheat/config.py",
                        "preamble": ["行1", ...],              # 模块头（docstring/imports/收敛常量）
                        "symbols": ["SAMPLE_RATE", ...]}]}

装配规则（保证逐字节、绝不伤字面量）:
  1. 每个符号 = 顶层 def/class/单目标 Name 赋值，AST 闭区间整行切片;
  2. 符号上方紧邻的纯注释/空行块一并上溯带走（保留原叙事上下文）;
  3. 相邻符号的"注释扩展区"若重叠 → 合并成连续跨度，中间源码行原样保留;
  4. 跨度之间被跳过（未搬移/已核销）的代码行整体丢弃，只留两个空行;
  5. 任何行内容不被改写——没有全局文本替换，三引号字符串内部空行安全;
  6. spec 里的符号在源码中找不到 → 报错退出 1（防 typo 静默漏搬）。
"""
import ast
import json
import os
import sys

from parity import read_lines


def top_symbols(lines):
    """name -> (kind, start, end) 1 起行号闭区间，与 parity 同源"""
    src = "\n".join(lines)
    tree = ast.parse(src)
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, []).append(("def", node.lineno, node.end_lineno))
        elif isinstance(node, ast.ClassDef):
            out.setdefault(node.name, []).append(("class", node.lineno, node.end_lineno))
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.setdefault(t.id, []).append(("const", node.lineno, node.end_lineno))
    return out


def span_start(lines, s):
    """符号上方紧邻的注释/空行块起点（0 起行号）；s 为符号 1 起行号"""
    i = s - 2                      # s-1 是符号 0 起行号，向上走
    while i >= 0 and (lines[i].strip() == "" or lines[i].strip().startswith("#")):
        i -= 1
    return i + 1


def merge_spans(spans):
    """[start0, end0) 半开区间列表，重叠/贴邻合并 → 源码行原样保留"""
    spans = sorted(spans)
    merged = []
    for st, en in spans:
        if merged and st <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], en))
        else:
            merged.append((st, en))
    return merged


def assemble(build):
    src_path = build["source"]
    lines = read_lines(src_path)
    syms = top_symbols(lines)
    missing = [n for n in build["symbols"] if n not in syms]
    if missing:
        print(f"  !! {src_path} 中找不到符号: {missing}", file=sys.stderr)
        return False
    spans = []
    for name in build["symbols"]:
        _, s, e = syms[name][0]
        spans.append((span_start(lines, s), e))     # [0 起, 闭区间→半开)
    blocks = []
    for st, en in merge_spans(spans):
        blk = lines[st:en]
        while blk and blk[0].strip() == "":         # 跨度过头上溯的裸空行去掉
            blk.pop(0)
        blocks.append(blk)

    out_path = build["out"]
    out = []
    for ln in build.get("preamble", []):
        out.append(ln.rstrip("\n"))
    out.append("")
    first = True
    for blk in blocks:
        if not first:
            if not (out[-2:] == ["", ""]):
                while out and out[-1] == "":
                    out.pop()
                out.append("")
                out.append("")
        first = False
        for ln in blk:
            if out and out[-1] == "" and ln == "":   # 块内行首的连续空行收敛为一
                continue
            out.append(ln)
    while out and out[-1] == "":
        out.pop()
    text = "\n".join(out) + "\n"
    os.makedirs(os.path.dirname(out_path), exist_ok=True) if os.path.dirname(out_path) else None
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"  [ok] {src_path} → {out_path}  ({len(build['symbols'])} 符号, "
          f"{len(text.splitlines())} 行)")
    return True


def census(path):
    """列模块里 '用了但没定义/没导入' 的全局名（帮写 import 行）"""
    lines = read_lines(path)
    tree = ast.parse("\n".join(lines))
    used, bound = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                used.add(node.id)
            else:
                bound.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                bound.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                bound.add(a.asname or a.name)
    import builtins
    free = sorted(used - bound - set(dir(builtins)))
    print(f"[census] {path}: 使用但未定义/未导入的名字 {len(free)} 个")
    for n in free:
        print(f"    {n}")
    return free


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--symbols":
        for k, v in sorted(top_symbols(read_lines(argv[1])).items()):
            kind, s, e = v[0]
            print(f"{k}  ({kind} {s}-{e})")
        return 0
    if argv and argv[0] == "--census":
        return 1 if census(argv[1]) else 0
    with open(argv[0], encoding="utf-8") as f:
        spec = json.load(f)
    ok = True
    for b in spec["builds"]:
        if not assemble(b):
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

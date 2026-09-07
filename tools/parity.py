#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parity.py — 按符号(顶层 def/class/常量赋值)的源码切片对比工具。

行为等价门禁：重构是纯搬移，搬过去的每个函数/类/常量切片应逐字节等于源。
用法：
  python tools/parity.py --baseline A.py B.py -o baseline.json   # 两个单体互比(Step 0)
  python tools/parity.py --check 源.py 新模块.py [新模块2.py ...]  # 门禁：源里每个符号
                                                                # 若在任一新模块中出现必须切片相等(或差异⊆允许清单)
  python tools/parity.py --check 源.py -p interview_tool        # 对整个包目录做同样检查
  --allow allow.json   # {"符号名": [旧文件行号...]} 允许这些旧行在差异中出现(收敛编辑登记表)
退出码: 0=通过(无意外差异); 1=有意外差异。--baseline 总返回 0。
"""
import ast
import difflib
import json
import os
import sys

BOM = "﻿"


def read_lines(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        text = f.read()
    if text.startswith(BOM):
        text = text[len(BOM):]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.split("\n")


def slice_lines(lines, start, end):
    # ast 行号从 1 起、end 为闭区间; lines 索引从 0
    return lines[start - 1:end]


def iter_top_symbols(lines):
    """Yield (name, kind, start, end) 顶层 def/class/const-assign。"""
    src = "\n".join(lines)
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        print(f"  !! SyntaxError: {e}", file=sys.stderr)
        return
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, "def", node.lineno, node.end_lineno
        elif isinstance(node, ast.ClassDef):
            yield node.name, "class", node.lineno, node.end_lineno
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    # 常量 slab: 只是值部分, 不含前面的同名注释
                    yield t.id, "const", node.lineno, node.end_lineno


def collect(path, const_ok=True):
    lines = read_lines(path)
    syms = {}
    for name, kind, s, e in iter_top_symbols(lines):
        if kind == "const" and not const_ok:
            continue
        key = f"{kind}:{name}"
        syms.setdefault(key, []).append((slice_lines(lines, s, e), s))
    return lines, syms


def unidiff(old_lines, new_lines):
    return list(difflib.unified_diff(
        old_lines, new_lines, fromfile="old", tofile="new", lineterm=""))


def removed_old_numbers(diff, old_start):
    """unified diff 中 '删除/修改' 行的旧文件行号集合。"""
    n = old_start - 1  # diff 的旧行计数器, 从文件行 1 起
    removed = []
    for ln in diff:
        if ln.startswith("@@") or ln.startswith("---") or ln.startswith("+++"):
            continue
        if ln.startswith("-"):
            n += 1
            removed.append(n)
        elif ln.startswith("+"):
            pass
        else:
            n += 1
    return set(removed)


def check_pair(old_path, new_paths, allow=None):
    """old 中每个符号若出现在任一 new 里, 切片必须相等或差异⊆allow。"""
    old_lines, old_syms = collect(old_path)
    new_map = {}
    for np_ in new_paths:
        _, ns = collect(np_)
        for k, v in ns.items():
            new_map.setdefault(k, []).append((np_, v))
    old_name = os.path.basename(old_path)
    identical, diff, missing = [], [], []
    for key, occs in sorted(old_syms.items()):
        cands = new_map.get(key)
        if not cands:
            missing.append(key)
            continue
        # 同名多处(old 内重复)? 取第一个, 报出
        o_slice, o_start = occs[0]
        verdict_ok = False
        best = None                     # (npath, diff, reason) 展示用
        for npath, n_occs in cands:
            n_slice, n_start = n_occs[0]
            if o_slice == n_slice:      # 任一候选逐字节相等 = 通过
                identical.append(key)
                verdict_ok = True
                break
            d = unidiff(o_slice, n_slice)
            if allow is not None and key in allow:
                allowed_lines = set(allow[key])
                if "*" in allowed_lines:    # "*" = 整符号放行（收敛重写区, 如 def:main）
                    verdict_ok = True
                    reason = "allow['*'] 放行（收敛重写区）"
                    best = (npath, d, reason)
                    break
                rm = removed_old_numbers(d, o_start)
                if rm <= allowed_lines:
                    verdict_ok = True
                    reason = f"removed⊆allow[{len(rm)}/{len(allowed_lines)}]"
                    best = (npath, d, reason)
                    break
            if best is None:
                best = (npath, d, "??")
        if not verdict_ok:
            # 全部候选不相等且 diff 超出允许 → FAIL（展示第一个候选）
            npath, d, reason = best
            diff.append((key, o_start, npath, d, False, reason))
        elif best is not None:
            # allow 放行的收敛编辑：保留 OK 展示
            npath, d, reason = best
            diff.append((key, o_start, npath, d, True, reason))
    return old_name, identical, diff, missing


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--baseline":
        a, b = argv[1], argv[2]
        out = argv[4] if len(argv) > 3 and argv[3] == "-o" else None
        la, sa = collect(a)
        _, sb = collect(b)
        result = {"identical": [], "diff": {}, "only_in_a": [], "only_in_b": []}
        for key in sa:
            if key in sb:
                if sa[key][0][0] == sb[key][0][0]:
                    result["identical"].append(key)
                else:
                    result["diff"][key] = {
                        "a_start": sa[key][0][1], "b_start": sb[key][0][1],
                        "diff": unidiff(sa[key][0][0], sb[key][0][0])}
            else:
                result["only_in_a"].append(key)
        for key in sb:
            if key not in sa:
                result["only_in_b"].append(key)
        ident = len(result["identical"])
        print(f"[baseline] {a} vs {b}")
        print(f"  逐字节相同: {ident}  有差异: {len(result['diff'])}"
              f"  仅A有: {len(result['only_in_a'])}  仅B有: {len(result['only_in_b'])}")
        if out:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=1)
            print(f"  -> 基线 JSON 已写 {out}")
        return 0

    allow = None
    allow_i = argv.index("--allow") if "--allow" in argv else None
    if allow_i is not None:
        with open(argv[allow_i + 1], encoding="utf-8") as f:
            allow = json.load(f)
        argv = argv[:allow_i] + argv[allow_i + 2:]
    assert argv[0] == "--check"
    old_path = argv[1]
    if argv[2] == "-p":
        pkg = argv[3]
        new_paths = []
        for fn in sorted(os.listdir(pkg)):
            if fn.endswith(".py"):
                new_paths.append(os.path.join(pkg, fn))
    else:
        new_paths = argv[2:]
    old_name, identical, diff, missing = check_pair(old_path, new_paths, allow)

    print(f"[check] {old_name} vs {len(new_paths)} 模块")
    print(f"  相同: {len(identical)}  有差异: {len(diff)}  未迁移: {len(missing)}")
    fail = False
    for key, o_start, npath, d, ok, reason in diff:
        tag = "OK " if ok else "FAIL"
        if not ok:
            fail = True
        print(f"  [{tag}] {key} (旧行{o_start}) -> {npath}  {reason if not ok else ''}")
        if not ok:
            print(f"        removed 旧行号: {sorted(removed_old_numbers(d, o_start))}"
                  f"  (若为预期收敛编辑, 并入 --allow)")
        for ln in d[:16]:
            print(f"      {ln}")
        if len(d) > 16:
            print(f"      ... 共 {len(d)} 行")
    for key in missing:
        print(f"  [MISS] {key} 未在包中迁移")
    print("==> " + ("通过(无意外差异)" if not fail else "有意外差异, 禁止提交"))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())

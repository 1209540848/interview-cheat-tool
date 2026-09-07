#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""census.py — 未定义名扫描（pyflakes 替代，本机无 pyflakes）。

作用域感知检查：单趟递归遍历 AST，每层作用域收集绑定（参数/赋值/import/def/class 名/
推导式目标/with-as/except-as/global 上浮到 module）与 Load 引用；结束后逐引用沿作用域链
解析到 module 层 → builtins。解析不到 = 未定义名（漏 import / 打字错误），exit 1。

语义要点（对齐 pyflakes）：
  - 作用域内"任意位置有绑定"即视为已定义（不查使用前赋值——那是运行期问题）
  - class 体不参与闭包：方法/类内代码查名跳过 class 局部、直接到 module
  - 推导式/lambda 各自成层，target 不泄漏
  - from x import * 无法静态知道绑定 → 所在作用域引用全部放行（打印提示）

用法:
  python tools/census.py -p interview_tool     # 整包
  python tools/census.py a.py b.py              # 指定文件
输出空 = 干净。
"""
import ast
import builtins
import os
import sys

BUILTINS = set(dir(builtins)) | {
    "__name__", "__file__", "__doc__", "__builtins__", "__package__",
    "__spec__", "__loader__", "__cached__", "__path__", "__annotations__",
}


class Scope:
    __slots__ = ("kind", "parent", "module", "bind", "refs", "star")

    def __init__(self, kind, parent, module):
        self.kind = kind            # module / function / class / comp
        self.parent = parent
        self.module = module
        self.bind = set()
        self.refs = []              # [(name, lineno)]
        self.star = False           # from x import * 出现在本作用域

    def lookup(self, name):
        """沿链找绑定：class 的 bind 只对本类体可见（链上不会出现别的 class，
        parent 在建层时已投影到最近非 class 祖先；实测 3.12 类体可读外层函数局部）"""
        cur = self
        while cur is not None:
            if name in cur.bind:
                return True
            cur = cur.parent
        return False


def _skip_class(scope):
    """class 不参与闭包：链上所有 class 层都被跳过（类体名只对本类体可见）"""
    while scope is not None and scope.kind == "class":
        scope = scope.parent
    return scope


class Census:
    def __init__(self, path):
        self.path = path
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.tree = ast.parse(src, path)
        self.mod = Scope("module", None, None)
        self.mod.module = self.mod
        self.all = [self.mod]

    # ---------- 绑定辅助 ----------
    def _bind_targets(self, node, scope):
        if isinstance(node, ast.Name):
            scope.bind.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for e in node.elts:
                self._bind_targets(e, scope)
        elif isinstance(node, ast.Starred):
            self._bind_targets(node.value, scope)
        # Attribute/Subscript 目标不产生新名字绑定

    # ---------- 语句层 ----------
    def _stmt(self, node, scope):
        t = type(node)
        if t in (ast.FunctionDef, ast.AsyncFunctionDef):
            scope.bind.add(node.name)
            for d in node.decorator_list:
                self._expr(d, scope)
            a = node.args
            for d in a.defaults:
                self._expr(d, scope)
            for d in a.kw_defaults:
                if d is not None:
                    self._expr(d, scope)
            if node.returns is not None:
                self._expr(node.returns, scope)
            child = Scope("function", _skip_class(scope), scope.module)
            self.all.append(child)
            for arg in (list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)):
                child.bind.add(arg.arg)
            if a.vararg:
                child.bind.add(a.vararg.arg)
            if a.kwarg:
                child.bind.add(a.kwarg.arg)
            for s in node.body:
                self._stmt(s, child)
        elif t is ast.ClassDef:
            scope.bind.add(node.name)
            for d in node.decorator_list:
                self._expr(d, scope)
            child = Scope("class", _skip_class(scope), scope.module)  # 类体名不对外闭包
            self.all.append(child)
            for s in node.body:
                self._stmt(s, child)
        elif t is ast.Assign:
            for tg in node.targets:
                self._bind_targets(tg, scope)
            self._expr(node.value, scope)
        elif t is ast.AnnAssign:
            self._bind_targets(node.target, scope)   # Attribute 目标内部无 Name→无害
            if node.annotation is not None:
                self._expr(node.annotation, scope)
            if node.value is not None:
                self._expr(node.value, scope)
        elif t is ast.AugAssign:
            self._bind_targets(node.target, scope)
            self._expr(node.value, scope)
        elif t in (ast.For, ast.AsyncFor):
            self._bind_targets(node.target, scope)
            self._expr(node.iter, scope)
            for s in node.body:
                self._stmt(s, scope)
            for s in node.orelse:
                self._stmt(s, scope)
        elif t is ast.If:
            self._expr(node.test, scope)
            for s in node.body:
                self._stmt(s, scope)
            for s in node.orelse:
                self._stmt(s, scope)
        elif t is ast.While:
            self._expr(node.test, scope)
            for s in node.body:
                self._stmt(s, scope)
            for s in node.orelse:
                self._stmt(s, scope)
        elif t in (ast.With, ast.AsyncWith):
            for item in node.items:
                self._expr(item.context_expr, scope)
                if item.optional_vars is not None:
                    self._bind_targets(item.optional_vars, scope)
            for s in node.body:
                self._stmt(s, scope)
        elif t is ast.Try:
            for s in node.body:
                self._stmt(s, scope)
            for h in node.handlers:
                if h.type is not None:
                    self._expr(h.type, scope)
                if h.name:
                    scope.bind.add(h.name)
                for s in h.body:
                    self._stmt(s, scope)
            for s in node.orelse:
                self._stmt(s, scope)
            for s in node.finalbody:
                self._stmt(s, scope)
        elif t is ast.Raise:
            if node.exc is not None:
                self._expr(node.exc, scope)
            if node.cause is not None:
                self._expr(node.cause, scope)
        elif t is ast.Return:
            if node.value is not None:
                self._expr(node.value, scope)
        elif t is ast.Assert:
            self._expr(node.test, scope)
            if node.msg is not None:
                self._expr(node.msg, scope)
        elif t is ast.Expr:
            self._expr(node.value, scope)
        elif t is ast.Import:
            for a in node.names:
                scope.bind.add(a.asname or a.name.split(".")[0])
        elif t is ast.ImportFrom:
            for a in node.names:
                if a.name == "*":
                    scope.star = True
                else:
                    scope.bind.add(a.asname or a.name)
        elif t is ast.Global:
            # global 声明：绑定上浮到 module 层
            self.mod.bind.update(node.names)
        elif t is ast.Nonlocal:
            pass                    # 目标必须存在于父链 → 编译期已验；本层无需绑定
        elif t in (ast.Delete, ast.Pass, ast.Break, ast.Continue):
            pass
        else:                       # 未知语句兜底（如 3.10+ match）：按子节点分派
            for c in ast.iter_child_nodes(node):
                if isinstance(c, ast.stmt):
                    self._stmt(c, scope)
                else:
                    self._expr(c, scope)

    # ---------- 表达式层 ----------
    def _expr(self, node, scope):
        t = type(node)
        if t in (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp):
            child = Scope("comp", _skip_class(scope), scope.module)
            self.all.append(child)
            for gen in node.generators:
                self._bind_targets(gen.target, child)
                self._expr(gen.iter, child)
                for cond in gen.ifs:
                    self._expr(cond, child)
            if t is ast.DictComp:
                self._expr(node.key, child)
                self._expr(node.value, child)
            elif t is ast.GeneratorExp:
                self._expr(node.elt, child)
            else:
                self._expr(node.elt, child)
        elif t is ast.Lambda:
            a = node.args
            for d in a.defaults:
                self._expr(d, scope)        # defaults 在外层求值
            for d in a.kw_defaults:
                if d is not None:
                    self._expr(d, scope)
            child = Scope("function", _skip_class(scope), scope.module)
            self.all.append(child)
            for arg in (list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)):
                child.bind.add(arg.arg)
            if a.vararg:
                child.bind.add(a.vararg.arg)
            if a.kwarg:
                child.bind.add(a.kwarg.arg)
            self._expr(node.body, child)
        elif t is ast.NamedExpr:
            self._bind_targets(node.target, scope)
            self._expr(node.value, scope)
        elif t is ast.Name:
            if isinstance(getattr(node, "ctx", None), ast.Load):
                scope.refs.append((node.id, node.lineno))
        else:
            for c in ast.iter_child_nodes(node):
                self._expr(c, scope)

    # ---------- 主流程 ----------
    def run(self):
        for s in self.tree.body:
            self._stmt(s, self.mod)
        found = []
        seen = set()
        for sc in self.all:
            if sc.star:
                print(f"  [!] {self.path}: from-import * 出现在 {sc.kind} 作用域,"
                      f" 该层引用跳过未定义检查")
                continue
            for name, lineno in sc.refs:
                if name in BUILTINS:
                    continue
                if name in sc.bind or sc.lookup(name):
                    continue
                if (lineno, name) not in seen:
                    seen.add((lineno, name))
                    found.append((lineno, name, sc.kind))
        found.sort()
        return found


def scan_file(path):
    return Census(path).run()


def main():
    try:                                        # GBK 控制台不乱码
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = sys.argv[1:]
    files = []
    if args and args[0] == "-p":
        pkg = args[1]
        files = [os.path.join(pkg, fn) for fn in sorted(os.listdir(pkg))
                 if fn.endswith(".py")]
    else:
        files = args
    total = 0
    for path in files:
        try:
            bad = scan_file(path)
        except SyntaxError as e:
            print(f"census: {path}: SyntaxError {e}", file=sys.stderr)
            total += 1
            continue
        if bad:
            print(f"census: {path}")
            for lineno, name, kind in bad:
                print(f"  [L{lineno}] {name}  ({kind} 作用域, 未定义/未导入)")
        total += len(bad)
    if total:
        print(f"==> 发现 {total} 个问题, 禁止提交")
        return 1
    print(f"census: {len(files)} 个文件干净 (0 未定义名)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

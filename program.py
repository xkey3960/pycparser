#!/usr/bin/python
"""program.py — 多 .c 文件程序装载/链接/运行（M6/S1）

把多个 C 源文件解析为 FileAST 列表，按"链接三阶段"注册到解释器全局状态，
再调用入口函数运行：

  1a. 类型收集：typedef / struct / union / enum 全量注册（跨文件类型可见）
  1b. 函数收集：FuncDef 全部注册（只注册不执行体 → 前向引用可用）
  2.  全局变量：Decl / DeclList 声明（此时函数表已齐，init 可调函数）

设计依据：19.work-space/pycparser/设计文档-多文件支持.md §2.1 ~ §3.3

用法：
    from program import CProgram
    prog = CProgram(["lib.c", "main.c"])
    prog.load()           # 解析
    prog.link()           # 链接（1a 类型 → 1b 函数 → 2 全局变量）
    result = prog.run()   # 运行 main()
"""

from pycparser import c_ast
from pycparser import parse_file

from pycparserext import ext_c_parser

from typesys import g_types, type_of_decl, types_equivalent

import execute as exe_mod
from execute import execute


class CProgram:
    """一组 C 源文件组成的程序（共享解释器全局状态）。"""

    def __init__(self, files, entry='main', cpp_path='gcc', cpp_args=None,
                 parser=None, encoding=None, strict=False):
        self.files = list(files)
        self.entry = entry
        self.cpp_path = cpp_path
        self.cpp_args = cpp_args if cpp_args is not None \
            else ['-E', '-Iutils/fake_libc_include']
        self.parser = parser if parser is not None else ext_c_parser.GnuCParser()
        self.encoding = encoding
        self.strict = strict
        self.asts = []                 # list[FileAST]
        self.entry_file = None         # 入口函数所在文件
        self._entry_candidates = []    # 入口 FuncDef 节点列表
        self._func_names = {}          # 函数名 → is_static（跨文件重名检测）

    # ==================== 阶段 1：解析 ====================

    def load(self):
        """解析全部文件 → FileAST[]（逐文件 cpp 预处理 + parser）。"""
        for f in self.files:
            ast = parse_file(f, use_cpp=True, cpp_path=self.cpp_path,
                             cpp_args=self.cpp_args, parser=self.parser,
                             encoding=self.encoding)
            self.asts.append(ast)
        return self.asts

    # ==================== 阶段 2：链接 ====================

    def link(self):
        """链接三阶段：1a 类型 → 1b 函数 → 2 全局变量（+冲突检测 + 入口定位）。"""
        # 1a 类型收集：跨文件类型可见（typedef/struct/union/enum 全量注册 + 冲突检测）
        for ast in self.asts:
            for ext in ast.ext or []:
                if isinstance(ext, (c_ast.Typedef, c_ast.Struct, c_ast.Union, c_ast.Enum)):
                    if isinstance(ext, c_ast.Typedef) and ext.name:
                        self._check_typedef_conflict(ext)
                    elif ext.name:
                        self._check_tag_conflict(ext)
                    execute(ext)
        # 1b 函数收集：FuncDef 全部注册（只注册不执行体 → 前向引用可用；重名检测）
        for ast in self.asts:
            for ext in ast.ext or []:
                if isinstance(ext, c_ast.FuncDef):
                    self._check_func_conflict(ext)
                    execute(ext)
        # 2 全局变量 / 编译期检查（此时函数表已齐，init 可调函数）
        for ast in self.asts:
            for ext in ast.ext or []:
                if isinstance(ext, (c_ast.Decl, c_ast.DeclList)):
                    for d in _iter_decls(ext):
                        if self._should_declare_global(d):
                            execute(d)
                elif isinstance(ext, c_ast.StaticAssert):
                    execute(ext)
        # 入口定位：多个文件定义入口时以第一个为准（重新注册覆盖）
        self._resolve_entry()
        if len(self._entry_candidates) > 1:
            print(f"[warn] 多个文件定义入口 '{self.entry}'，取第一个: {self.entry_file}")
            execute(self._entry_candidates[0])
        return self

    # ---------- 冲突检测（S2） ----------

    def _warn_or_raise(self, msg, force_raise=False):
        """冲突处理：strict 或强制时抛错，否则打印 [warn]。"""
        if force_raise or self.strict:
            raise AssertionError(msg)
        print(f"[warn] {msg}")

    def _check_typedef_conflict(self, ext):
        """typedef 重名：相同（types_equivalent）静默；冲突警告/strict 报错。"""
        existing = g_types.aliases.get(ext.name)
        if existing is None:
            return
        new_t = type_of_decl(ext.type)
        if not types_equivalent(existing, new_t):
            self._warn_or_raise(
                f"typedef '{ext.name}' 冲突: {existing.name} vs {new_t.name}")

    def _check_tag_conflict(self, ext):
        """struct/union/enum 标签重名：成员签名不同 → 冲突警告/strict 报错。"""
        if isinstance(ext, c_ast.Struct):
            kind = 'struct'
        elif isinstance(ext, c_ast.Union):
            kind = 'union'
        else:
            kind = 'enum'
        if not g_types.has_tag(kind, ext.name):
            return
        existing = g_types.lookup_tag(kind, ext.name)
        if kind in ('struct', 'union'):
            if ext.decls is None or not existing.is_complete():
                return
            ast_names = [d.name for d in ext.decls
                         if isinstance(d, c_ast.Decl) and d.name]
            cur_names = [m.name for m in existing.members]
        else:  # enum
            if ext.values is None:
                return
            ast_names = [e.name for e in ext.values.enumerators or []]
            cur_names = list(existing.constants.keys())
        if ast_names != cur_names:
            self._warn_or_raise(
                f"{kind} '{ext.name}' 冲突: 成员 {cur_names} vs {ast_names}")

    def _check_func_conflict(self, ext):
        """函数重名：非 static 非入口重复 → 报错；static 重复 → 警告（后者覆盖）；
        入口重复由 _resolve_entry 处理（警告 + 取第一）。"""
        name = ext.decl.name
        storage = ext.decl.storage or []
        is_static = 'static' in storage
        if name not in self._func_names:
            self._func_names[name] = is_static
            return
        prev_static = self._func_names[name]
        if is_static or prev_static:
            self._warn_or_raise(
                f"static 函数 '{name}' 跨文件重名，后者覆盖（v1）")
        elif name == self.entry:
            pass  # 入口函数重名：_resolve_entry 警告 + 取第一个
        else:
            self._warn_or_raise(
                f"函数 '{name}' 重复定义（C 语义: 重复定义）", force_raise=True)

    def _should_declare_global(self, decl):
        """全局变量声明判定：重复裸声明（tentative）跳过保留首个；
        带 init 重名 → 冲突警告（取后者）。"""
        if not decl.name:
            return False
        try:
            exe_mod.g_scope.get(decl.name)
        except AssertionError:
            return True  # 首次声明
        if decl.init is None:
            return False  # 重复的裸声明（C tentative definition）：保留首个定义
        self._warn_or_raise(
            f"全局变量 '{decl.name}' 重复初始化定义（取后者）")
        return True

    def _resolve_entry(self):
        """定位入口函数（默认 'main'）：找不到报错，多个记录候选。"""
        found = []
        for ast, path in zip(self.asts, self.files):
            for ext in ast.ext or []:
                if isinstance(ext, c_ast.FuncDef) and ext.decl.name == self.entry:
                    found.append((path, ext))
        if not found:
            raise AssertionError(
                f"未找到入口函数 '{self.entry}'（文件: {self.files}）")
        self.entry_file = found[0][0]
        self._entry_candidates = [ext for _, ext in found]

    # ==================== 阶段 3：运行 ====================

    def run(self, *args):
        """调用入口函数；args 为整型参数列表。

        注意：用 exe_mod.g_functions 取模块级全局（setup_global_scope 会重赋值，
        import 绑定的旧引用会过期）。
        """
        if self.entry not in exe_mod.g_functions:
            raise AssertionError(f"入口函数 '{self.entry}' 未注册（是否已 link？）")
        args_node = None
        if args:
            args_node = c_ast.ExprList(exprs=[
                c_ast.Constant(type='int', value=str(a)) for a in args])
        call = c_ast.FuncCall(name=c_ast.ID(name=self.entry), args=args_node)
        return execute(call)

    # ==================== 便捷 ====================

    @classmethod
    def load_and_run(cls, files, entry='main', **kw):
        prog = cls(files, entry, **kw)
        prog.load()
        prog.link()
        return prog.run()


def _iter_decls(node):
    """把顶层 Decl / DeclList 展开为单个 Decl 列表（供冲突检测逐项处理）。"""
    if isinstance(node, c_ast.Decl):
        return [node]
    if isinstance(node, c_ast.DeclList):
        return [d for d in (node.decls or []) if isinstance(d, c_ast.Decl)]
    return []

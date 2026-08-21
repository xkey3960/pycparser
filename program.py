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

from typesys import g_types, type_of_decl, types_equivalent, ensure_complete

from sources import (
    g_source_index,
    _warn_or_raise,
    check_typedef_conflict,
    check_tag_conflict,
    check_func_conflict,
)

import execute as exe_mod
from execute import execute, InterpreterError


class CProgram:
    """一组 C 源文件组成的程序（共享解释器全局状态）。

    lazy=True（默认，L3）：跳过 link，load() 建零检查符号索引，run() 时按需激活
    （Python import 语义，见 设计文档-惰性解析.md 方案 B）；冲突检测在文件激活时
    "用到才检"。
    lazy=False：需显式 link() 全量注册（含全量冲突检测，strict 模式）。
    """

    def __init__(self, files, entry='main', cpp_path='gcc', cpp_args=None,
                 parser=None, encoding=None, strict=False, lazy=True):
        self.files = list(files)
        self.entry = entry
        self.cpp_path = cpp_path
        self.cpp_args = cpp_args if cpp_args is not None \
            else ['-E', '-Iutils/fake_libc_include']
        self.parser = parser if parser is not None else ext_c_parser.GnuCParser()
        self.encoding = encoding
        self.strict = strict
        self.lazy = lazy
        self.asts = []                 # list[FileAST]
        self.entry_file = None         # 入口函数所在文件
        self._entry_candidates = []    # 入口 FuncDef 节点列表
        self._func_names = {}          # 函数名 → is_static（跨文件重名检测）

    # ==================== 阶段 1：解析 ====================

    def load(self):
        """解析全部文件 → FileAST[]（逐文件 cpp 预处理 + parser）。

        lazy 模式下同时建立零检查符号索引（只扫名字，不解析类型），
        并把 strict/entry 配置传给索引（激活时的冲突检测用）。
        """
        for f in self.files:
            ast = parse_file(f, use_cpp=True, cpp_path=self.cpp_path,
                             cpp_args=self.cpp_args, parser=self.parser,
                             encoding=self.encoding)
            self.asts.append(ast)
        if self.lazy:
            g_source_index.build(self.asts, self.files)
            g_source_index.strict = self.strict
            g_source_index.entry = self.entry
        return self.asts

    # ==================== 阶段 2：链接 ====================

    def link(self):
        """链接三阶段：1a 类型 → 1b 函数 → 2 全局变量（+冲突检测 + 入口定位）。

        L4 类型惰性：1a 注册类型（struct/union 只注册不布局）；1a 后全量补全
        （ensure_complete）——link 是显式全量检查（eager），类型布局/重定义
        冲突在此暴露；惰性模式（run 自动 activate_all）才延迟到首次使用。
        """
        # 1a 类型收集：跨文件类型可见（typedef/struct/union/enum/裸类型定义 全量注册 + 冲突检测）
        self._link_tags = set()      # 本次 1a 定义过的 struct/union 标签名（补全范围）
        for ast in self.asts:
            for ext in ast.ext or []:
                if isinstance(ext, (c_ast.Typedef, c_ast.Struct, c_ast.Union, c_ast.Enum)) \
                        or (isinstance(ext, c_ast.Decl) and ext.name is None):
                    # 裸类型定义（struct S {...}; 解析为 Decl(name=None)）由 ExeDecl 注册
                    if isinstance(ext, c_ast.Typedef) and ext.name:
                        self._check_typedef_conflict(ext)
                    elif getattr(ext, 'name', None):
                        self._check_tag_conflict(ext)
                    self._link_tags |= _collect_tag_names(ext)
                    execute(ext)
        # 1a 后：L4 全量补全（eager link = 全量检查：布局本次定义的 struct/union，
        # 暴露类型错误/重定义冲突；跨测试残留标签不碰）
        self._complete_all_tags()
        # 1a 后：顶层 _Static_assert 编译期检查（BUG-3：类型已注册，sizeof 可算）
        for ast in self.asts:
            for ext in ast.ext or []:
                if isinstance(ext, c_ast.StaticAssert):
                    execute(ext)
        # 1b 函数收集：FuncDef 全部注册（只注册不执行体 → 前向引用可用；重名检测）
        for ast, path in zip(self.asts, self.files):
            saved_file = exe_mod.g_current_file
            exe_mod.g_current_file = path            # S4：static 归属当前文件
            try:
                for ext in ast.ext or []:
                    if isinstance(ext, c_ast.FuncDef):
                        self._check_func_conflict(ext)
                        execute(ext)
            finally:
                exe_mod.g_current_file = saved_file
        # 2 全局变量 / 编译期检查（此时函数表已齐，init 可调函数）
        for ast, path in zip(self.asts, self.files):
            saved_file = exe_mod.g_current_file
            exe_mod.g_current_file = path
            try:
                for ext in ast.ext or []:
                    if isinstance(ext, (c_ast.Decl, c_ast.DeclList)):
                        for d in _iter_decls(ext):
                            if self._should_declare_global(d):
                                execute(d)
            finally:
                exe_mod.g_current_file = saved_file
        # 入口定位：多个文件定义入口时以第一个为准（重新注册覆盖）
        self._resolve_entry()
        if len(self._entry_candidates) > 1:
            print(f"[warn] 多个文件定义入口 '{self.entry}'，取第一个: {self.entry_file}")
            execute(self._entry_candidates[0])
        return self

    def _complete_all_tags(self):
        """全量补全（L4 link 专用）：布局本次 link 定义过的 struct/union 标签。

        类型错误（成员/维度未定义符号）与重定义冲突在此暴露——
        link = eager 全量检查（与惰性模式的"用时才检"对照）。
        只补全 _link_tags 记录的名字，避免补到跨测试残留标签。
        """
        for kind in ('struct', 'union'):
            for name in list(self._link_tags):
                if g_types.has_tag(kind, name):
                    ensure_complete(g_types.lookup_tag(kind, name))

    # ---------- 冲突检测（S2） ----------

    def _warn_or_raise(self, msg, force_raise=False):
        """冲突处理：strict 或强制时抛错，否则打印 [warn]（委托共享实现）。"""
        _warn_or_raise(msg, self.strict, force_raise)

    def _check_typedef_conflict(self, ext):
        """typedef 重名：相同（types_equivalent）静默；冲突警告/strict 报错。"""
        check_typedef_conflict(ext, self.strict)

    def _check_tag_conflict(self, ext):
        """struct/union/enum 标签重名：成员签名不同 → 冲突警告/strict 报错。"""
        check_tag_conflict(ext, self.strict)

    def _check_func_conflict(self, ext):
        """函数重名：非 static 非入口重复 → 报错；static 重复 → 警告（后者覆盖）；
        入口重复由 _resolve_entry 处理（警告 + 取第一）。"""
        check_func_conflict(ext.decl.name, ext.decl.storage,
                            self.entry, self._func_names, self.strict)

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

        lazy 模式（L4 全局 eager + 类型 lazy）：启动装载**全部**文件
        （activate_all：每个文件 1a 类型注册 → 1b 函数 → 2 全局 init）——
        全局变量在启动时全部初始化（C 语义）；但 struct/union 只注册不布局，
        类型检查延迟到首次真正使用（ensure_complete）——无需 link。
        非 lazy 模式：要求已 link（现行行为）。

        注意：用 exe_mod.g_functions 取模块级全局（setup_global_scope 会重赋值，
        import 绑定的旧引用会过期）。
        """
        if self.lazy:
            self._resolve_entry()                       # 名字扫描（零解析）
            if self.entry not in exe_mod.g_functions:
                # 未 link：启动装载全部文件（全局 eager；类型检查惰性）
                g_source_index.activate_all()
        if self.entry not in exe_mod.g_functions:
            raise AssertionError(f"入口函数 '{self.entry}' 未注册（是否已 link？）")
        args_node = None
        if args:
            args_node = c_ast.ExprList(exprs=[
                c_ast.Constant(type='int', value=str(a)) for a in args])
        call = c_ast.FuncCall(name=c_ast.ID(name=self.entry), args=args_node)
        try:
            return execute(call)
        except InterpreterError as e:
            # QOL-1：打印源码位置 + 调用链，然后原样抛出（测试 except 兼容）
            self._report_error(e)
            raise

    def _report_error(self, e):
        """QOL-1：打印 [error] 源码位置 + 调用链（异常携带的栈快照）。"""
        msg = getattr(e, 'message', str(e))
        print(f"[error] {msg}")
        stack = getattr(e, '_call_stack', None) or []
        if stack:
            lines = []
            for frame in stack:
                coord = getattr(frame, 'call_coord', None)
                loc = f" at {coord}" if coord is not None else ""
                lines.append(f"调用 {frame.func_name}(){loc}")
            print("调用链:")
            for ln in lines:
                print(f"  {ln}")

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


def _collect_tag_names(node):
    """递归收集声明节点中出现的 struct/union 标签名（L4 link 全量补全范围）。

    覆盖：顶层 Struct/Union、typedef struct {...} 的内嵌标签、Decl(name=None)
    裸定义、以及成员中内联定义的复合类型。enum 不收集（enum 注册即完整）。
    """
    found = set()
    if isinstance(node, (c_ast.Struct, c_ast.Union)) and node.name:
        found.add(node.name)
    for attr in ('type', 'decls', 'ext'):
        child = getattr(node, attr, None)
        if child is None:
            continue
        if isinstance(child, list):
            for c in child:
                found |= _collect_tag_names(c)
        else:
            found |= _collect_tag_names(child)
    return found


# ==================== CLI（S4） ====================

if __name__ == '__main__':
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    entry = 'main'
    if '--entry' in sys.argv:
        entry = sys.argv[sys.argv.index('--entry') + 1]
    if not args:
        print("用法: python program.py <a.c> [b.c ...] [--entry 函数名]")
        sys.exit(1)
    prog = CProgram(args, entry=entry)
    prog.load()
    result = prog.run()
    print(result)

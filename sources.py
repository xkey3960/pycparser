#!/usr/bin/python
"""sources.py — 符号索引与文件级惰性装载（L1，设计文档-惰性解析.md 方案 B）

CProgram.load()（lazy 模式）建立**零检查**的符号索引：符号名 → 定义文件
（只扫 ext 名字，不解析类型，因此坏文件不会阻断索引建立）。

运行中首次用到某文件中的函数/变量时，激活（import）该文件：
按序注册该文件的 类型 → 函数 → 全局变量（文件内三阶段，幂等，环守卫）。

Python 语义类比：文件激活 ≈ import 该模块（顶层定义按序注册）；
跨文件惰性 = 用到哪个模块才 import 哪个。
"""

from pycparser import c_ast


class SourceIndex:
    """符号索引 + 文件激活状态机。"""

    def __init__(self):
        self._asts = {}        # 路径 -> FileAST
        self._funcs = {}       # 函数名 -> (路径, FuncDef)
        self._tags = {}        # (kind, 标签名) -> (路径, 节点)   （L2 类型钩子用）
        self._typedefs = {}    # typedef 名 -> (路径, Typedef)    （L2 类型钩子用）
        self._globals = {}     # 全局变量名 -> (路径, Decl)
        self._state = {}       # 路径 -> 'unloaded' | 'loading' | 'loaded'

    # ---------- 建立索引（零检查：只扫 ext 名字，不解析类型） ----------

    def reset(self):
        self._asts.clear()
        self._funcs.clear()
        self._tags.clear()
        self._typedefs.clear()
        self._globals.clear()
        self._state.clear()

    def build(self, asts, paths):
        """从 FileAST 列表建立符号索引（重复符号取第一个，注册时后者覆盖）。"""
        self.reset()
        for ast, path in zip(asts, paths):
            self._asts[path] = ast
            self._state[path] = 'unloaded'
            for ext in ast.ext or []:
                if isinstance(ext, c_ast.FuncDef) and ext.decl.name:
                    self._funcs.setdefault(ext.decl.name, (path, ext))
                elif isinstance(ext, c_ast.Typedef) and ext.name:
                    self._typedefs.setdefault(ext.name, (path, ext))
                elif isinstance(ext, (c_ast.Struct, c_ast.Union, c_ast.Enum)) and ext.name:
                    kind = ('struct' if isinstance(ext, c_ast.Struct)
                            else 'union' if isinstance(ext, c_ast.Union) else 'enum')
                    self._tags.setdefault((kind, ext.name), (path, ext))
                elif isinstance(ext, c_ast.Decl) and ext.name:
                    self._globals.setdefault(ext.name, (path, ext))
        return self

    # ---------- 惰性装载 ----------

    def activate_for(self, name):
        """按函数名/全局变量名触发文件装载（幂等；非源符号 no-op）。"""
        loc = self._funcs.get(name) or self._globals.get(name)
        if loc:
            self.activate(loc[0])

    def activate_for_type(self, kind, name):
        """按类型标签/typedef 名触发文件装载（L2 类型钩子用）。"""
        loc = self._tags.get((kind, name)) or self._typedefs.get(name)
        if loc:
            self.activate(loc[0])

    def activate(self, path):
        """装载（import）一个文件：1a 类型 → 1b 函数 → 2 全局。幂等 + 环守卫。

        环：'loading' 期间再被引用 → 直接返回（该文件函数已在 1b 注册、
        类型可经"不完整→补全"兜底，因此部分装载可安全引用）。
        """
        state = self._state.get(path)
        if state in ('loaded', 'loading'):
            return
        self._state[path] = 'loading'
        ast = self._asts[path]
        from execute import execute   # 延迟导入避免循环依赖

        # 1a 类型（含裸类型定义 Decl(name=None)）
        for ext in ast.ext or []:
            if isinstance(ext, (c_ast.Typedef, c_ast.Struct, c_ast.Union, c_ast.Enum)) \
                    or (isinstance(ext, c_ast.Decl) and ext.name is None):
                execute(ext)
        # 1b 函数
        for ext in ast.ext or []:
            if isinstance(ext, c_ast.FuncDef):
                execute(ext)
        # 2 全局变量 / 编译期断言（init 可触发其他文件激活）
        for ext in ast.ext or []:
            if isinstance(ext, (c_ast.Decl, c_ast.DeclList)):
                execute(ext)
            elif isinstance(ext, c_ast.StaticAssert):
                execute(ext)
        self._state[path] = 'loaded'

    # ---------- 查询 ----------

    @property
    def state(self):
        return self._state

    def entry_path(self, entry):
        """入口函数所在文件（按名字，零解析）；无则 None。"""
        loc = self._funcs.get(entry)
        return loc[0] if loc else None


# 全局单例（execute.py 的调用钩子与 CProgram.load 共用）
g_source_index = SourceIndex()

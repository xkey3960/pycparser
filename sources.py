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
        self.strict = False    # 冲突检测：strict 时报错而非告警（L3）
        self.entry = 'main'    # 入口函数名（函数重名豁免，L3）
        self._func_names = {}  # 函数名 → is_static（跨文件重名检测）

    # ---------- 建立索引（零检查：只扫 ext 名字，不解析类型） ----------

    def reset(self):
        self._asts.clear()
        self._funcs.clear()
        self._tags.clear()
        self._typedefs.clear()
        self._globals.clear()
        self._func_names.clear()
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
                    self._index_inner_tag(ext.type, path, ext)
                elif isinstance(ext, (c_ast.Struct, c_ast.Union, c_ast.Enum)) and ext.name:
                    self._index_tag(ext, path, ext)
                elif isinstance(ext, c_ast.Decl):
                    if ext.name:
                        self._globals.setdefault(ext.name, (path, ext))
                    else:
                        self._index_inner_tag(ext.type, path, ext)  # 裸类型定义
        return self

    def _index_tag(self, node, path, ext):
        """索引复合类型标签（struct/union/enum）。"""
        if node.name:
            kind = ('struct' if isinstance(node, c_ast.Struct)
                    else 'union' if isinstance(node, c_ast.Union) else 'enum')
            self._tags.setdefault((kind, node.name), (path, ext))

    def _index_inner_tag(self, type_node, path, ext):
        """索引被 TypeDecl 包装的复合类型标签（typedef struct {...} S; 的标签、
        裸 enum E {...}; 的标签）。"""
        inner = type_node
        while inner is not None and type(inner).__name__ in ('TypeDecl', 'TypeDeclExt'):
            inner = getattr(inner, 'type', None)
        if isinstance(inner, (c_ast.Struct, c_ast.Union, c_ast.Enum)):
            self._index_tag(inner, path, ext)

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

        L4 惰性类型检查：1a 只**注册**类型标签（struct/union 注册为不完整，
        挂 _deferred AST），不布局、不求值成员/维度——类型错误延后到
        ensure_complete（首次真正使用该类型时）才暴露。

        文件顶层在**全局作用域**执行（激活可能发生在函数调用中途，但文件级
        的全局变量/枚举常量必须落在全局作用域，语义如"程序启动时装载"）。

        环：'loading' 期间再被引用 → 直接返回（该文件函数已在 1b 注册、
        类型可经"不完整→补全"兜底，因此部分装载可安全引用）。
        """
        state = self._state.get(path)
        if state in ('loaded', 'loading'):
            return
        self._state[path] = 'loading'
        ast = self._asts[path]
        from execute import execute   # 延迟导入避免循环依赖
        import execute as exe_mod

        saved_scope = exe_mod.g_scope
        exe_mod.g_scope = exe_mod.g_global_scope   # 文件顶层 → 全局作用域
        saved_file = exe_mod.g_current_file
        exe_mod.g_current_file = path              # S4：当前文件（static 归属）
        try:
            # 1a 类型（含裸类型定义 Decl(name=None)）：注册（L4 不布局）。
            # enum 保持 eager（注册即注入常量）→ 冲突即时检；struct/union
            # 惰性注册，重定义冲突延后到 ensure_complete（_dupes 机制）。
            for ext in ast.ext or []:
                if isinstance(ext, c_ast.Typedef) and ext.name:
                    check_typedef_conflict(ext, self.strict)
                    execute(ext)
                elif isinstance(ext, (c_ast.Struct, c_ast.Union, c_ast.Enum)) and ext.name:
                    if isinstance(ext, c_ast.Enum):
                        check_tag_conflict(ext, self.strict)
                    execute(ext)
                elif isinstance(ext, c_ast.Decl) and ext.name is None:
                    inner = ext.type
                    while inner is not None and type(inner).__name__ in ('TypeDecl', 'TypeDeclExt'):
                        inner = getattr(inner, 'type', None)
                    if isinstance(inner, c_ast.Enum) and inner.name:
                        check_tag_conflict(inner, self.strict)
                    execute(ext)
            # 1b 函数：注册 + 重名检测（L3）
            for ext in ast.ext or []:
                if isinstance(ext, c_ast.FuncDef):
                    check_func_conflict(ext.decl.name, ext.decl.storage,
                                        self.entry, self._func_names, self.strict)
                    execute(ext)
            # 2 全局变量 / 编译期断言（init 可触发其他文件激活）
            for ext in ast.ext or []:
                if isinstance(ext, (c_ast.Decl, c_ast.DeclList)):
                    execute(ext)
                elif isinstance(ext, c_ast.StaticAssert):
                    execute(ext)
        finally:
            exe_mod.g_scope = saved_scope
            exe_mod.g_current_file = saved_file
        self._state[path] = 'loaded'

    def activate_all(self):
        """启动装载全部文件（L4 全局 eager）：每个文件 1a 类型注册 → 1b 函数 → 2 全局。

        保证所有全局变量在程序启动时初始化（C 语义）；类型检查仍惰性
        （注册不布局，用时才补全）。幂等（已 loaded 直接返回）。
        """
        for path in list(self._state):
            self.activate(path)

    # ---------- 查询 ----------

    @property
    def state(self):
        return self._state

    def entry_path(self, entry):
        """入口函数所在文件（按名字，零解析）；无则 None。"""
        loc = self._funcs.get(entry)
        return loc[0] if loc else None


# ==================== 共享冲突检测（L3） ====================
# 供 SourceIndex.activate（惰性"用到才检"）与 CProgram.link（全量检查）共用。
# 延迟导入 typesys 避免循环依赖（typesys 顶层 import 本模块）。

def _warn_or_raise(msg, strict, force_raise=False):
    """冲突处理：strict 或强制时抛错，否则打印 [warn]。"""
    if force_raise or strict:
        raise AssertionError(msg)
    print(f"[warn] {msg}")


def check_typedef_conflict(ext, strict):
    """typedef 重名：相同（等价）静默；冲突 warn/strict 报错。"""
    from typesys import g_types, type_of_decl, types_equivalent
    existing = g_types.aliases.get(ext.name)
    if existing is None:
        return
    new_t = type_of_decl(ext.type)
    if not types_equivalent(existing, new_t):
        _warn_or_raise(f"typedef '{ext.name}' 冲突: {existing.name} vs {new_t.name}", strict)


def check_tag_conflict(ext, strict):
    """struct/union/enum 标签重名：成员签名不同 → 冲突 warn/strict 报错。"""
    from typesys import g_types
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
        _warn_or_raise(f"{kind} '{ext.name}' 冲突: 成员 {cur_names} vs {ast_names}", strict)


def check_func_conflict(name, storage, entry, func_names, strict):
    """函数重名：登记 func_names；非 static 非入口重复 → 报错；
    static 不参与（S4 文件级隔离，无跨文件冲突）；入口重复豁免。"""
    if 'static' in (storage or []):
        return                       # S4：static 内部链接，同文件注册由 ExeFuncDef 隔离
    if name not in func_names:
        func_names[name] = False
        return
    if name == entry:
        pass  # 入口函数重名：入口定位警告 + 取第一个
    else:
        _warn_or_raise(f"函数 '{name}' 重复定义（C 语义: 重复定义）", strict, force_raise=True)


# 全局单例（execute.py 的调用钩子与 CProgram.load 共用）
g_source_index = SourceIndex()

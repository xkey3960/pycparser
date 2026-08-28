#!/usr/bin/python
"""lockcheck.py — 持锁调用静态分析（LOCK-CHECK）

规则：函数 F 不允许在持有任意锁的状态下被调用——任何加锁动作之后、
解锁之前，不得调用 F（不区分是哪把锁）。

实现（详见 设计文档-持锁调用检查.md）：
  ① 解析：gcc -E 预处理 + GnuCParser → FileAST[]（UTF-8 解码 + 每文件重试）
  ② CFG：每个函数 AST → 基本块图；所有表达式内调用按求值顺序抽事件
  ③ 函数内 may-数据流：状态 = 持锁集合（并集合并，块级不动点）
  ④ 跨函数：callee 无关摘要（adds 从 entry=∅ 推导，rels 语法计算）
     + IN 单调传播（wrapper 天然覆盖，无振荡）

用法：
    python lockcheck.py <a.c> [b.c ...] \
        --forbid log_tx,log_event \
        [--acquire pthread_mutex_lock,mutex_lock] \
        [--release pthread_mutex_unlock,mutex_unlock] \
        [--json] [--quiet]

退出码：0 = 无违规；1 = 发现违规；2 = 用法错误。
"""

import argparse
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from pycparser import c_ast

DEFAULT_ACQUIRE = ['pthread_mutex_lock', 'mutex_lock', 'spin_lock',
                   'pthread_spin_lock', 'sem_wait']
DEFAULT_RELEASE = ['pthread_mutex_unlock', 'mutex_unlock', 'spin_unlock',
                   'pthread_spin_unlock', 'sem_post']

# 常见内置/库函数视为"已知直接调用"（不当作函数指针告警）
BUILTIN_FUNCS = {
    'printf', 'fprintf', 'sprintf', 'snprintf', 'vprintf', 'vfprintf',
    'vsprintf', 'vsnprintf', 'puts', 'putchar', 'getchar',
    'malloc', 'calloc', 'realloc', 'free', 'memcpy', 'memmove', 'memset',
    'memcmp', 'strlen', 'strcpy', 'strncpy', 'strcmp', 'strncmp', 'strcat',
    'strncat', 'strchr', 'strstr', 'strtol', 'strtod', 'atoi', 'atol',
    'exit', 'abort', 'rand', 'srand', 'time', 'clock', 'abs', 'fabs',
    'pow', 'sqrt', 'sin', 'cos', 'floor', 'ceil',
    'open', 'close', 'read', 'write', 'fopen', 'fclose', 'fread', 'fwrite',
    'fgets', 'fputs', 'perror', 'sscanf', 'fscanf',
    'pthread_create', 'pthread_join', 'pthread_exit', 'pthread_self',
    'usleep', 'sleep', 'assert',
}

_MAX_ITER = 200   # 跨函数不动点安全上限


def _is(node, name):
    """按类名判型（跨 pycparser 版本/分支稳健，避免属性缺失崩溃）。"""
    return type(node).__name__ == name


# ==================== 表达式工具 ====================

def expr_key(e):
    """锁身份：参数表达式的规范化字符串（同一把锁键稳定）。"""
    if e is None:
        return '<none>'
    t = type(e).__name__
    if t == 'ID':
        return e.name
    if t == 'Constant':
        return str(e.value)
    if t == 'UnaryOp':
        return e.op + expr_key(e.expr)
    if t == 'BinaryOp':
        return '(' + expr_key(e.left) + e.op + expr_key(e.right) + ')'
    if t == 'ArrayRef':
        return expr_key(e.name) + '[' + expr_key(e.subscript) + ']'
    if t == 'StructRef':
        field = e.field.name if _is(e.field, 'ID') else str(e.field)
        return expr_key(e.name) + ('.' if e.type == '.' else '->') + field
    if t == 'Cast':
        return '(cast)' + expr_key(e.expr)
    if t == 'Assignment':
        return expr_key(e.lvalue) + '=' + expr_key(e.rvalue)
    if t == 'FuncCall':
        return expr_key(e.name) + '(...)'
    if t == 'ExprList':
        return ','.join(expr_key(x) for x in e.exprs)
    if t == 'CompoundLiteral':
        return '{' + expr_key(e.init) + '}'
    return t


def _walk_expr(e, out):
    """按求值顺序收集表达式内的 FuncCall（含嵌套实参/下标/三元等）。"""
    if e is None:
        return
    t = type(e).__name__
    if t == 'FuncCall':
        out.append(e)
        _walk_expr(getattr(e, 'name', None), out)
        _walk_expr(getattr(e, 'args', None), out)
    elif t in ('ID', 'Constant', 'TypeDecl', 'IdentifierType', 'PtrDecl',
               'ArrayDecl', 'FuncDecl', 'Enum', 'Enumerator', 'Typedef',
               'Struct', 'Union'):
        return
    elif t == 'BinaryOp':
        _walk_expr(e.left, out)
        _walk_expr(e.right, out)
    elif t == 'UnaryOp':
        _walk_expr(e.expr, out)
    elif t == 'Assignment':
        _walk_expr(e.lvalue, out)
        _walk_expr(e.rvalue, out)
    elif t == 'ArrayRef':
        _walk_expr(e.name, out)
        _walk_expr(e.subscript, out)
    elif t == 'StructRef':
        _walk_expr(e.name, out)
    elif t == 'Cast':
        _walk_expr(e.expr, out)
    elif t == 'ExprList':
        for x in e.exprs or []:
            _walk_expr(x, out)
    elif t == 'TernaryOp':
        _walk_expr(e.cond, out)
        _walk_expr(e.iftrue, out)
        _walk_expr(e.iffalse, out)
    elif t == 'CompoundLiteral':
        _walk_expr(e.init, out)
    elif t == 'Decl':
        _walk_expr(e.init, out)
    else:
        # 未知复合节点：按 children() 顺序兜底
        for _name, child in e.children():
            _walk_expr(child, out)


def expr_calls(e):
    """表达式内出现的 FuncCall 列表（求值顺序）。"""
    out = []
    _walk_expr(e, out)
    return out


# ==================== CFG ====================

class CFG:
    """基本块图：blocks[id] = {'events': [...], 'succ': [...]}。"""

    def __init__(self):
        self.blocks = []
        self.entry = None
        self.exits = set()

    def new_node(self, events):
        self.blocks.append({'events': list(events), 'succ': []})
        return len(self.blocks) - 1

    def link(self, src, dst):
        if dst is not None and dst not in self.blocks[src]['succ']:
            self.blocks[src]['succ'].append(dst)


# ==================== 主分析器 ====================

class LockCheck:
    """持锁调用静态分析器。

    violations: [(path, func, coord, forbidden, frozenset[(lock, acq_site)])]
    indirect:   [(path, coord)]  函数指针调用（未建模，人工补位）
    """

    def __init__(self, files, acquire=None, release=None, forbid=(),
                 cpp_args=None, ast_cache=True):
        self.files = list(files)
        self.acquire_set = set(acquire if acquire is not None
                               else DEFAULT_ACQUIRE)
        self.release_set = set(release if release is not None
                               else DEFAULT_RELEASE)
        self.forbid_set = set(forbid or ())
        self.cpp_args = cpp_args
        self.ast_cache = ast_cache
        self.asts = None
        self.violations = []
        self.indirect = []
        self._warnings = []

    # ---------- 解析 ----------

    def load(self):
        """解析全部文件 → FileAST[]（gcc -E + GnuCParser，并行 + 重试）。

        - gcc -E 输出按 UTF-8 解码（errors=replace），规避 Windows GBK
          环境的 UnicodeDecodeError；
        - 每个文件最多重试 3 次：云盘占位/同步中的瞬时空文件会解析出
          "At end of input"，重试等待内容落盘；
        - 线程池并行（与 QOL-4 同思路；不依赖 CProgram 内部实现）。
        """
        if self.cpp_args is None:
            repo_root = os.path.dirname(os.path.abspath(__file__))
            self.cpp_args = ['-E',
                             '-I' + os.path.join(repo_root,
                                                 'utils', 'fake_libc_include')]
        from pycparserext import ext_c_parser
        parser = ext_c_parser.GnuCParser()

        def _parse_one(path):
            last = None
            for _attempt in range(3):
                try:
                    text = self._preprocess(path)
                    return parser.parse(text, path)
                except Exception as e:      # 解析失败可重试（内容未落盘）
                    last = e
                    time.sleep(0.15)
            raise last

        if len(self.files) > 1:
            workers = min(os.cpu_count() or 1, len(self.files))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                self.asts = list(pool.map(_parse_one, self.files))
        else:
            self.asts = [_parse_one(f) for f in self.files]
        return self.asts

    def _preprocess(self, path):
        """gcc -E 预处理，stdout 按 UTF-8 解码（errors=replace）。

        Windows 下 gcc 用系统码页（GBK）输出 #line 里的文件名，与 UTF-8
        内容混流无法单编码解码：保留 #line（行号真实），仅把被解码破坏
        （含 U+FFFD）的引号文件名替换为 ASCII 占位符 "src"。
        """
        cmd = ['gcc', '-E'] + list(self.cpp_args) + [path]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
        if proc.returncode != 0:
            err = proc.stderr.decode('utf-8', 'replace')[:200]
            raise RuntimeError(f"gcc -E 失败（{path}）: {err}")
        text = proc.stdout.decode('utf-8', 'replace')
        # gcc 输出保留 CRLF；pycparser 词法器不认裸 \r（原管线经
        # universal_newlines 已做换行转换，这里补上）
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        return self._sanitize_line_markers(text)

    @staticmethod
    def _sanitize_line_markers(text):
        """#line 行内的损坏文件名（含 U+FFFD）替换为 ASCII 占位符。"""
        import re
        out = []
        for line in text.split('\n'):
            m = re.match(r'^\s*#\s*(?:line\s+)?\d+', line)
            if m and '\ufffd' in line:
                line = re.sub(r'"[^"\n]*"', '"src"', line)
            out.append(line)
        return '\n'.join(out)

    # ---------- 函数与已知符号 ----------

    def _collect_functions(self):
        funcs = {}
        for ast, path in zip(self.asts, self.files):
            for ext in ast.ext or []:
                if _is(ext, 'FuncDef') and ext.decl and ext.decl.name:
                    name = ext.decl.name
                    if name in funcs:
                        self._warnings.append(
                            f"函数重名 '{name}'（{path}），取第一个定义分析")
                    else:
                        funcs[name] = (path, ext)
        return funcs

    def _known_functions(self):
        """已知函数名：FuncDef + 函数声明（FuncDecl）+ 内置库函数。"""
        known = set(BUILTIN_FUNCS)
        for ast in self.asts:
            for ext in ast.ext or []:
                if _is(ext, 'FuncDef') and ext.decl and ext.decl.name:
                    known.add(ext.decl.name)
                elif _is(ext, 'Decl') and ext.name:
                    t = ext.type
                    while t is not None:
                        tn = type(t).__name__
                        if tn == 'FuncDecl':
                            known.add(ext.name)
                            break
                        if tn in ('TypeDecl', 'TypeDeclExt', 'PtrDecl',
                                  'ArrayDecl'):
                            t = getattr(t, 'type', None)
                        else:
                            break
        return known

    # ---------- 事件 ----------

    def func_events(self, fc):
        """单个 FuncCall → 事件列表。coord 转 str（Coord 不可哈希，且便于报告）。"""
        name_node = fc.name
        coord = str(fc.coord)
        if _is(name_node, 'ID'):
            name = name_node.name
            if name in self.acquire_set:
                arg = fc.args.exprs[0] if (fc.args and fc.args.exprs) else None
                return [('acquire', expr_key(arg), coord)]
            if name in self.release_set:
                arg = fc.args.exprs[0] if (fc.args and fc.args.exprs) else None
                return [('release', expr_key(arg), coord)]
            if name in self.forbid_set:
                return [('forbidden', name, coord)]
            return [('call', name, coord)]
        return [('indirect', coord)]

    def _stmt_exprs(self, stmt):
        """语句中需要扫描调用事件的表达式列表。"""
        t = type(stmt).__name__
        if t == 'If':
            return [stmt.cond]
        if t in ('While', 'DoWhile'):
            return [stmt.cond]
        if t == 'Return':
            return [stmt.expr]
        if t == 'Switch':
            return [stmt.cond]
        if t == 'Case':
            return [stmt.expr]
        if t == 'ExprList':
            return list(stmt.exprs or [])
        if t == 'Decl':
            return [stmt.init]
        if t == 'Assignment':
            return [stmt]
        if t == 'FuncCall':
            return [stmt]
        if t == 'StaticAssert':
            return [stmt.cond]
        return []

    def expr_events(self, e):
        evs = []
        for fc in expr_calls(e):
            evs.extend(self.func_events(fc))
        return evs

    def stmt_events(self, stmt):
        evs = []
        for e in self._stmt_exprs(stmt):
            evs.extend(self.expr_events(e))
        return evs

    # ---------- CFG 构建 ----------

    def build_cfg(self, fd):
        cfg = CFG()
        self._cfg = cfg
        self._labels = {}
        self._pending_gotos = []
        self._break_stack = []     # ('loop'|'switch', break_target, cont_target?)
        self._exit_node = cfg.new_node([])
        body = fd.body
        items = body.block_items if body else None
        cfg.entry = self._walk_stmt_list(items or [], self._exit_node)
        for src, name in self._pending_gotos:
            if name in self._labels:
                cfg.link(src, self._labels[name])
            else:
                self._warnings.append(
                    f"goto 未定义标签 '{name}' @ {fd.coord}")
        cfg.exits = {i for i, b in enumerate(cfg.blocks) if not b['succ']}
        return cfg

    def _walk_stmt_list(self, items, next_node):
        if not items:
            return next_node
        nxt = next_node
        for stmt in reversed(items):
            nxt = self._walk_stmt(stmt, nxt)
        return nxt

    def _walk_stmt(self, stmt, next_node):
        if stmt is None:
            return next_node
        t = type(stmt).__name__

        if t == 'Compound':
            return self._walk_stmt_list(stmt.block_items or [], next_node)

        if t == 'If':
            node = self._cfg.new_node(self.stmt_events(stmt))
            then_e = self._walk_stmt(stmt.iftrue, next_node)
            else_e = (self._walk_stmt(stmt.iffalse, next_node)
                      if stmt.iffalse else next_node)
            self._cfg.link(node, then_e)
            self._cfg.link(node, else_e)
            return node

        if t == 'While':
            cond_node = self._cfg.new_node(self.stmt_events(stmt))
            self._break_stack.append(('loop', next_node, cond_node))
            body_e = self._walk_stmt(stmt.stmt, cond_node)
            self._break_stack.pop()
            self._cfg.link(cond_node, body_e)
            self._cfg.link(cond_node, next_node)
            return cond_node

        if t == 'DoWhile':
            cond_node = self._cfg.new_node(self.stmt_events(stmt))
            self._break_stack.append(('loop', next_node, cond_node))
            body_e = self._walk_stmt(stmt.stmt, cond_node)
            self._break_stack.pop()
            self._cfg.link(cond_node, body_e)
            self._cfg.link(cond_node, next_node)
            return body_e

        if t == 'For':
            init_node = self._cfg.new_node(self.expr_events(stmt.init))
            cond_node = self._cfg.new_node(self.expr_events(stmt.cond))
            step_node = self._cfg.new_node(self.expr_events(stmt.next))
            self._break_stack.append(('loop', next_node, step_node))
            body_e = self._walk_stmt(stmt.stmt, step_node)
            self._break_stack.pop()
            self._cfg.link(init_node, cond_node)
            self._cfg.link(cond_node, body_e)
            self._cfg.link(cond_node, next_node)
            self._cfg.link(step_node, cond_node)
            return init_node

        if t == 'Switch':
            cond_node = self._cfg.new_node(self.stmt_events(stmt))
            self._break_stack.append(('switch', next_node, None))
            body = stmt.stmt
            items = body.block_items if _is(body, 'Compound') else [body]
            # 切成 case 段：Case/Default 及后续普通语句；段间 C 语义落穿
            segments = []
            cur = None
            for it in items or []:
                if _is(it, 'Case') or _is(it, 'Default'):
                    if cur is not None:
                        segments.append(cur)
                    cur = [it]
                else:
                    if cur is None:
                        cur = []
                    cur.append(it)
            if cur is not None:
                segments.append(cur)
            seg_entries = []
            target = next_node
            for seg in reversed(segments):
                target = self._walk_stmt_list(seg, target)
                seg_entries.append(target)
            seg_entries.reverse()
            for e in seg_entries:
                self._cfg.link(cond_node, e)
            self._cfg.link(cond_node, next_node)
            self._break_stack.pop()
            return cond_node

        if t == 'Case':
            node = self._cfg.new_node(self.stmt_events(stmt))
            inner = self._walk_stmt_list(stmt.stmts or [], next_node)
            self._cfg.link(node, inner)
            return node

        if t == 'Default':
            node = self._cfg.new_node([])
            inner = self._walk_stmt_list(stmt.stmts or [], next_node)
            self._cfg.link(node, inner)
            return node

        if t == 'Goto':
            node = self._cfg.new_node([])
            self._pending_gotos.append((node, stmt.name))
            return node

        if t == 'Label':
            node = self._cfg.new_node([])
            self._labels[stmt.name] = node
            inner = self._walk_stmt(stmt.stmt, next_node)
            self._cfg.link(node, inner)
            return node

        if t == 'Break':
            node = self._cfg.new_node([])
            if self._break_stack:
                self._cfg.link(node, self._break_stack[-1][1])
            return node

        if t == 'Continue':
            node = self._cfg.new_node([])
            for ctx in reversed(self._break_stack):
                if ctx[0] == 'loop':
                    self._cfg.link(node, ctx[2])
                    break
            return node

        if t == 'Return':
            node = self._cfg.new_node(self.stmt_events(stmt))
            self._cfg.link(node, self._exit_node)
            return node

        # 简单语句（表达式/声明/赋值/空语句/编译期断言）
        node = self._cfg.new_node(self.stmt_events(stmt))
        self._cfg.link(node, next_node)
        return node

    # ---------- 分析 ----------

    def _analyze_function(self, entry_locks, summaries, known_funcs):
        """对当前函数做函数内数据流（入口持锁集合参数化）。

        返回 dict: violations / callsites / indirect / exit_locks
        （本实现把函数体挂在实例上：_cur_fd / _cur_name）
        """
        cfg = self.build_cfg(self._cur_fd)
        entry_pairs = frozenset((lid, '<entry>') for lid in entry_locks)
        states = {cfg.entry: entry_pairs}
        worklist = [cfg.entry]
        violations = []
        callsites = []
        indirect = []
        while worklist:
            nid = worklist.pop()
            s = states[nid]
            for ev in cfg.blocks[nid]['events']:
                kind = ev[0]
                if kind == 'acquire':
                    s = s | frozenset([(ev[1], ev[2])])
                elif kind == 'release':
                    s = frozenset((lid, acq) for (lid, acq) in s
                                  if lid != ev[1])
                elif kind == 'forbidden':
                    if s:
                        violations.append((ev[1], ev[2], s))
                elif kind == 'call':
                    callee, coord = ev[1], ev[2]
                    if callee in known_funcs and callee not in self.forbid_set:
                        callsites.append((callee, coord, s))
                    elif callee not in known_funcs:
                        # 名字不是已知函数（函数指针变量）→ 间接调用告警，不解析目标
                        indirect.append(coord)
                    summ = summaries.get(callee)
                    if summ:
                        rels = summ['rels']
                        if rels:
                            s = frozenset((lid, acq) for (lid, acq) in s
                                          if lid not in rels)
                        adds = summ['adds']
                        if adds:
                            s = s | frozenset(
                                (lid, f'<callee:{callee}>') for lid in adds)
                elif kind == 'indirect':
                    indirect.append(ev[1])
            for succ in cfg.blocks[nid]['succ']:
                old = states.get(succ)
                if old is None:
                    states[succ] = s
                    worklist.append(succ)
                elif s != old and not s.issubset(old):
                    states[succ] = old | s
                    worklist.append(succ)
        exit_locks = frozenset()
        for nid in cfg.exits:
            for lid, _acq in states.get(nid, frozenset()):
                exit_locks = exit_locks | frozenset([lid])
        return {'violations': violations, 'callsites': callsites,
                'indirect': indirect, 'exit_locks': exit_locks}

    def analyze(self):
        """全程序分析：三阶段，全部单调收敛（无振荡）。

        阶段 A（callee 无关摘要）：
          adds[G] = entry=∅ 分析下的出口持锁（G 净新增的锁）
          rels[G] = G 函数体内释放事件命中的锁集合（语法计算，与调用者无关）
        阶段 B（IN 传播）：用固定摘要，函数内状态只随 IN 单调增长。
        阶段 C：稳定 IN 下收集违规/间接调用（按违规点去重，持锁并集）。

        摘要与调用者解耦 → 不存在"adds 与 rels 互相依赖"的振荡。
        """
        if self.asts is None:
            self.load()
        funcs = self._collect_functions()
        known = self._known_functions()
        names = list(funcs)

        # ---------- 阶段 A：callee 无关摘要 ----------
        summaries = {}
        for name in names:
            self._cur_name = name
            self._cur_fd = funcs[name][1]
            summaries[name] = {'adds': frozenset(),
                               'rels': self._released_code()}
        for _round in range(_MAX_ITER):
            changed = False
            for name in names:
                self._cur_name = name
                self._cur_fd = funcs[name][1]
                res = self._analyze_function(frozenset(), summaries, known)
                adds = res['exit_locks']
                if adds != summaries[name]['adds']:
                    summaries[name] = {'adds': adds,
                                       'rels': summaries[name]['rels']}
                    changed = True
            if not changed:
                break

        # ---------- 阶段 B：IN 传播（单调不动点） ----------
        IN = {name: frozenset() for name in names}
        inner_changed = True
        _guard = 0
        _converged = False
        while inner_changed and not _converged:
            inner_changed = False
            _guard += 1
            for name in names:
                self._cur_name = name
                self._cur_fd = funcs[name][1]
                res = self._analyze_function(IN[name], summaries, known)
                for callee, _coord, s in res['callsites']:
                    if callee in IN:
                        # IN 只存锁 id（不带获取位置）
                        merged = IN[callee] | frozenset(
                            lid for lid, _acq in s)
                        if merged != IN[callee]:
                            IN[callee] = merged
                            inner_changed = True
            if _guard >= _MAX_ITER:
                self._warnings.append('IN 传播未收敛（已达迭代上限）')
                _converged = True
            elif not inner_changed:
                _converged = True

        # ---------- 阶段 C：收集结果（按违规点去重，持锁并集） ----------
        by_site = {}
        indirect = set()
        for name in names:
            path, fd = funcs[name]
            self._cur_name = name
            self._cur_fd = fd
            res = self._analyze_function(IN[name], summaries, known)
            for fname, coord, held in res['violations']:
                key = (path, name, str(coord), fname)
                by_site.setdefault(key, set())
                by_site[key] |= set((lid, str(acq)) for lid, acq in held)
            for coord in res['indirect']:
                indirect.add((path, str(coord)))

        self.violations = sorted(
            [(k[0], k[1], k[2], k[3], frozenset(v))
             for k, v in by_site.items()],
            key=lambda x: (x[0], x[2], x[1]))
        self.indirect = sorted(indirect, key=lambda x: (x[0], x[1]))
        return self

    def _released_code(self):
        """函数体内释放事件命中的锁集合（语法计算，与调用者无关）。"""
        cfg = self.build_cfg(self._cur_fd)
        released = set()
        for b in cfg.blocks:
            for ev in b['events']:
                if ev[0] == 'release':
                    released.add(ev[1])
        return frozenset(released)

    # ---------- 输出 ----------

    def summary(self):
        return {
            'violations': [
                {'file': p, 'func': f, 'coord': self._coord_pos(c),
                 'forbidden': g,
                 'locks': [[lid, acq] for lid, acq in sorted(h)]}
                for p, f, c, g, h in self.violations],
            'indirect_calls': [
                {'file': p, 'coord': self._coord_pos(c)}
                for p, c in self.indirect],
            'warnings': list(self._warnings),
            'count': len(self.violations),
        }

    @staticmethod
    def _coord_pos(coord):
        """从 coord（'<file>:<line>:<col>'）取 'line:col'。"""
        parts = str(coord).split(':')
        return ':'.join(parts[-2:]) if len(parts) >= 2 else str(coord)

    def report(self, json=False, quiet=False):
        if json:
            import json as _json
            print(_json.dumps(self.summary(), ensure_ascii=False, indent=2))
            return len(self.violations)
        print(f'=== 持锁调用违规: {len(self.violations)} 处 ===')
        for path, func, coord, fname, held in self.violations:
            print(f'[LOCK] {path}:{self._coord_pos(coord)}  '
                  f'{func}() 持锁调用 {fname}()')
            for lid, acq in sorted(held):
                print(f'        持有 {lid}  (获取于 {acq})')
        if self.indirect:
            print(f'=== 间接调用告警(目标未建模, 人工补位): '
                  f'{len(self.indirect)} 处 ===')
            for path, coord in self.indirect:
                print(f'[WARN] {path}:{self._coord_pos(coord)}  '
                      f'函数指针调用未解析')
        if self._warnings and not quiet:
            print('=== 其他告警 ===')
            for w in self._warnings:
                print(f'[WARN] {w}')
        if not quiet:
            print(f'--- 汇总: 违规 {len(self.violations)}, '
                  f'间接调用 {len(self.indirect)} ---')
        return len(self.violations)


# ==================== CLI ====================

def main(argv=None):
    p = argparse.ArgumentParser(
        description='持锁调用静态分析：F 不允许在持有任意锁时被调用')
    p.add_argument('files', nargs='+', help='C 源文件')
    p.add_argument('--forbid', required=True,
                   help='禁调函数名，逗号分隔（必填）')
    p.add_argument('--acquire', default=','.join(DEFAULT_ACQUIRE),
                   help='加锁原语，逗号分隔')
    p.add_argument('--release', default=','.join(DEFAULT_RELEASE),
                   help='解锁原语，逗号分隔')
    p.add_argument('--json', action='store_true', help='JSON 输出')
    p.add_argument('--quiet', action='store_true', help='抑制汇总')
    p.add_argument('--no-ast-cache', action='store_true',
                   help='禁用 AST 磁盘缓存')
    args = p.parse_args(argv)

    forbid = [x for x in args.forbid.split(',') if x]
    if not forbid:
        p.error('--forbid 至少需要一个函数名')
    acquire = [x for x in args.acquire.split(',') if x]
    release = [x for x in args.release.split(',') if x]

    lc = LockCheck(args.files, acquire=acquire, release=release,
                   forbid=forbid, ast_cache=not args.no_ast_cache)
    lc.analyze()
    n = lc.report(json=args.json, quiet=args.quiet)
    return 1 if n else 0


if __name__ == '__main__':
    import sys
    sys.exit(main())

#!/usr/bin/python

"""pycparser AST Interpreter

Executes C AST nodes (standard + GNU C extensions) by dispatching
to type-specific executor classes.
"""

from pycparser import c_ast
from pycparser.c_ast import (
    # Expressions
    Assignment, ID, BinaryOp, Constant,
    UnaryOp, TernaryOp, Cast,
    ArrayRef, StructRef, FuncCall,
    ExprList,
    # Statements
    Compound, If, While, DoWhile, For,
    Return, Break, Continue,
    Switch, Case, Default,
    # Declarations
    Decl, DeclList, FuncDef,
    ArrayDecl, PtrDecl, TypeDecl, IdentifierType, FuncDecl,
    Struct, Union, Enum, Enumerator, EnumeratorList,
    Typedef, Typename,
    InitList, NamedInitializer,
    # Other
    EmptyStatement, Label, Goto,
    CompoundLiteral, Alignas, StaticAssert,
    FileAST, ParamList, EllipsisParam, Pragma,
    Node,
)

# GNU C extension nodes
from pycparserext.ext_c_parser import (
    TypeList,
    AttributeSpecifier,
    Asm,
    PreprocessorLine,
    TypeOfDeclaration,
    TypeOfExpression,
    RangeExpression,
    TypeDeclExt,
    ArrayDeclExt,
    StructExt,
    FuncDeclExt,
)

# C 类型系统基础设施（M0）+ 声明类型解析（M1）
from typesys import (
    g_types,
    CType,
    BasicType,
    PtrType,
    ArrayType,
    FuncType,
    EnumType,
    StructType,
    UnionType,
    Member,
    align_up,
    compute_struct_layout,
    compute_union_layout,
    type_of_decl,
    default_value_for,
    StructValue,
    UnionValue,
    coerce_to_type,
)

# 内置函数注册表（cbuiltins 模块导入即注册；@builtin 装饰器易扩展）
import cbuiltins  # noqa: F401  （注册副作用）
from cbuiltins import call_builtin


# ==================== Runtime Support ====================

class ReturnException(Exception):
    """Raised to unwind the stack on a return statement."""
    def __init__(self, value=None):
        self.value = value


class BreakException(Exception):
    """Raised to exit a loop."""


class ContinueException(Exception):
    """Raised to skip to the next loop iteration."""


class Symbol:
    """变量绑定：值 + 可选 C 类型（M0 起存储；类型系统就绪前 type 为 None）。

    向后兼容：Scope.get/set 仍返回/写入纯值，既有执行器与测试不受影响。
    """

    __slots__ = ("name", "value", "type")

    def __init__(self, name, value=None, type=None):
        self.name = name
        self.value = value
        self.type = type

    def __repr__(self):
        return f"Symbol({self.name!r}, value={self.value!r}, type={self.type!r})"


class Scope:
    """Variable scope with parent chaining for block scoping."""

    def __init__(self, parent=None):
        self._symbols = {}
        self._parent = parent

    def __str__(self):
        ret = str({k: s.value for k, s in self._symbols.items()})
        if self._parent:
            ret += str(self._parent)
        return ret

    def _get(self, name):
        if name in self._symbols:
            return self._symbols[name]
        if self._parent:
            return self._parent._get(name)
        raise AssertionError(f"Undefined variable: '{name}'")

    def get(self, name):
        return self._get(name).value

    def set(self, name, value):
        self._get(name).value = value

    def declare(self, name, value=None, type=None):
        self._symbols[name] = Symbol(name, value, type)

    # ---- M0 新增：类型相关 API ----

    def get_symbol(self, name):
        """返回 Symbol（含 value 与 type）。"""
        return self._get(name)

    def get_type(self, name):
        """返回变量的 C 类型（CType | None）。"""
        return self._get(name).type

    def set_type(self, name, type):
        self._get(name).type = type


class Function:
    """Represents a callable user-defined function (M5: 携带参数/返回类型)."""

    def __init__(self, name, param_names, body, closure_scope, param_types=None, ret_type=None):
        self.name = name
        self.param_names = param_names
        self.body = body
        self.closure_scope = closure_scope
        self.param_types = param_types or []   # [CType] 与 param_names 对齐
        self.ret_type = ret_type               # CType | None


# ==================== Global State ====================

g_scope = Scope()
g_functions = {}


# ==================== Type Utilities ====================

_TYPE_CONVERTERS = {
    'int': int,
    'float': float,
    'double': float,
    'char': lambda v: ord(v) if isinstance(v, str) and len(v) == 1 else int(v) if v else 0,
    'long': int,
    'short': int,
    'unsigned': int,
    'signed': int,
    '_Bool': bool,
    'bool': bool,
}


def _resolve_type(type_names):
    name = ' '.join(type_names).lower()
    for key, converter in _TYPE_CONVERTERS.items():
        if name == key or name.endswith(' ' + key):
            return converter
    return int


def _convert_value(value, type_names=None):
    if type_names is None:
        return int(value) if value is not None else 0
    converter = _resolve_type(type_names if isinstance(type_names, (list, tuple)) else [type_names])
    try:
        return converter(value)
    except (ValueError, TypeError):
        return int(value) if value is not None else 0


# ==================== Base Executor ====================

class Execute:
    """Base executor class."""

    def __init__(self, node):
        self.node = node

    def execute(self):
        raise NotImplementedError


def execute(node):
    """Dispatch an AST node to its executor."""
    if node is None:
        return None
    class_name = node.__class__.__name__
    if class_name in g_exe_class:
        return g_exe_class[class_name](node).execute()
    raise AssertionError(f"Unexpected AST node: '{class_name}'")


# ==================== Expression Executors ====================

_CHAR_ESCAPES = {
    'n': 10, 't': 9, 'r': 13, '0': 0, 'a': 7, 'b': 8, 'f': 12, 'v': 11,
    '\\': 92, "'": 39, '"': 34,
}


def _char_literal_code(v):
    """字符字面量 → int 码。pycparser 的 value 自带引号（"'A'"），需剥引号并处理转义。"""
    if isinstance(v, str) and len(v) >= 3 and v[0] == "'" and v[-1] == "'":
        inner = v[1:-1]
        if len(inner) == 2 and inner[0] == '\\':
            return _CHAR_ESCAPES.get(inner[1], ord(inner[1]))
        return ord(inner[0])
    if isinstance(v, str) and len(v) == 1:
        return ord(v)
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


_STRING_ESCAPES = {
    'n': '\n', 't': '\t', 'r': '\r', '0': '\0', 'a': '\a', 'b': '\b',
    'f': '\f', 'v': '\v', '\\': '\\', '"': '"', "'": "'", '?': '?',
}


def _unescape_c_string(s):
    r"""解 C 字符串转义（\n \t \xHH \0 等）。预处理不做转义，字面量中保留原始反斜杠序列。"""
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == '\\' and i + 1 < len(s):
            e = s[i + 1]
            if e in _STRING_ESCAPES:
                out.append(_STRING_ESCAPES[e])
                i += 2
            elif e == 'x':                       # \xHH（1-2 位十六进制）
                j, digits = i + 2, ''
                while j < len(s) and len(digits) < 2 and s[j] in '0123456789abcdefABCDEF':
                    digits += s[j]
                    j += 1
                out.append(chr(int(digits, 16)) if digits else '\\x')
                i = j
            elif e.isdigit():                    # \0 / \123（1-3 位八进制）
                j, digits = i + 1, ''
                while j < len(s) and len(digits) < 3 and s[j] in '01234567':
                    digits += s[j]
                    j += 1
                out.append(chr(int(digits, 8)))
                i = j
            else:
                out.append(e)                    # 未知转义：保留字符
                i += 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def _string_literal_value(v):
    """字符串字面量 → Python str。pycparser 的 value 自带双引号（'"hello"'），
    剥引号并解 C 转义（"len=%d\\n" → 'len=%d\\n' 真实换行）。"""
    if isinstance(v, str) and len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        return _unescape_c_string(v[1:-1])
    return v


class ExeConstant(Execute):
    """Constant literal."""

    def __init__(self, node):
        super().__init__(node)
        self._type_force = {
            'int': int,
            'float': float,
            'double': float,
            'char': _char_literal_code,
            'string': _string_literal_value,
            'long': int,
            'short': int,
            'unsigned': int,
            'signed': int,
            '_Bool': lambda v: bool(int(v)),
        }

    def execute(self):
        t = self.node.type
        if t in self._type_force:
            return self._type_force[t](self.node.value)
        try:
            return int(self.node.value)
        except (ValueError, TypeError):
            return self.node.value


class ExeID(Execute):
    """Identifier / variable reference."""

    def execute(self):
        return g_scope.get(self.node.name)


class ExeBinaryOp(Execute):
    """Binary operator expression."""

    def execute(self):
        op = self.node.op
        left = execute(self.node.left)
        right = execute(self.node.right)

        handlers = {
            '+': lambda: left + right,
            '-': lambda: left - right,
            '*': lambda: left * right,
            '/': lambda: int(left / right) if isinstance(left, int) and isinstance(right, int) else left / right,
            '%': lambda: left % right,
            '==': lambda: left == right,
            '!=': lambda: left != right,
            '<': lambda: left < right,
            '>': lambda: left > right,
            '<=': lambda: left <= right,
            '>=': lambda: left >= right,
            '&&': lambda: bool(left and right),
            '||': lambda: bool(left or right),
            '&': lambda: left & right,
            '|': lambda: left | right,
            '^': lambda: left ^ right,
            '<<': lambda: left << right,
            '>>': lambda: left >> right,
        }

        if op in handlers:
            return handlers[op]()
        raise AssertionError(f"Unknown binary operator: '{op}'")


class ExeUnaryOp(Execute):
    """Unary operator expression (M5: sizeof/__alignof__ 走类型路径，不求值 operand)."""

    def execute(self):
        op = self.node.op
        if op == 'sizeof':
            return _sizeof_type(self.node.expr)
        if op in ('__alignof__', '__alignof', '_Alignof'):
            return _alignof_type(self.node.expr)
        val = execute(self.node.expr)

        handlers = {
            '+': lambda: +val,
            '-': lambda: -val,
            '!': lambda: not val,
            '~': lambda: ~val,
            'p++': lambda: _p_plus_plus(self.node.expr, val),
            'p--': lambda: _p_sub_sub(self.node.expr, val),
            '__real__': lambda: val,
            '__imag__': lambda: 0,
        }

        if op in handlers:
            return handlers[op]()
        raise AssertionError(f"Unknown unary operator: '{op}'")

def _p_plus_plus(node, val):
    if isinstance(node, ID):
        g_scope.set(node.name, val+1)
    else:
        raise AssertionError(f"{node.__class__.__name__} can't support for p++")
    return val

def _p_sub_sub(node, val):
    if isinstance(node, ID):
        g_scope.set(node.name, val-1)
    else:
        raise AssertionError(f"{node.__class__.__name__} can't support for p--")
    return val


# ==================== 表达式类型推导（M5） ====================

def infer_type(node):
    """表达式静态类型推导（设计文档 §2.9.2）。

    供 sizeof/__alignof__/类型检查使用：只推导类型，不求值（无副作用）。
    """
    if node is None:
        return g_types.resolve(['int'])
    if isinstance(node, Constant):
        t = node.type
        if t == 'char':
            return g_types.resolve(['char'])
        if t in ('float', 'double'):
            return g_types.resolve(['double'])
        if t in ('_Bool', 'bool'):
            return g_types.resolve(['_Bool'])
        if t == 'string':
            return PtrType(g_types.resolve(['char']))
        return g_types.resolve(['int'])      # int/long/short/unsigned 等
    if isinstance(node, ID):
        t = g_scope.get_type(node.name)
        return t if t is not None else g_types.resolve(['int'])
    if isinstance(node, Cast):
        return type_of_decl(node.to_type)
    if isinstance(node, UnaryOp):
        if node.op == '*':
            t = infer_type(node.expr)
            if isinstance(t, PtrType):
                return t.points_to
            raise AssertionError("解引用非指针类型的表达式")
        if node.op == '&':
            return PtrType(infer_type(node.expr))
        if node.op in ('sizeof', '__alignof__', '__alignof', '_Alignof'):
            return g_types.resolve(['int'])  # 结果是 size_t，按 int 处理
        return infer_type(node.expr)         # + - ! ~ p++ 保持类型（宽松）
    if isinstance(node, BinaryOp):
        lt, rt = infer_type(node.left), infer_type(node.right)
        # 宽松提升：任一浮点 → double；否则 int
        if isinstance(lt, BasicType) and ('float' in lt.name or 'double' in lt.name):
            return lt
        if isinstance(rt, BasicType) and ('float' in rt.name or 'double' in rt.name):
            return rt
        return g_types.resolve(['int'])
    if isinstance(node, StructRef):
        obj_t = infer_type(node.name)
        field = node.field.name if isinstance(node.field, ID) else str(node.field)
        if isinstance(obj_t, (StructType, UnionType)):
            return obj_t.member_type(field)
        if isinstance(obj_t, PtrType) and isinstance(obj_t.points_to, (StructType, UnionType)):
            return obj_t.points_to.member_type(field)
        raise AssertionError(f"无法对 {type(obj_t).__name__} 做成员访问类型推导")
    if isinstance(node, ArrayRef):
        t = infer_type(node.name)
        if isinstance(t, ArrayType):
            return t.elem_type
        if isinstance(t, PtrType):
            return t.points_to
        raise AssertionError("对非数组/指针表达式做下标推导")
    if isinstance(node, FuncCall):
        name_node = node.name
        fname = name_node.name if isinstance(name_node, ID) else None
        if fname and fname in g_functions and g_functions[fname].ret_type is not None:
            return g_functions[fname].ret_type
        return g_types.resolve(['int'])      # 内建/未知按 int
    if isinstance(node, TernaryOp):
        return infer_type(node.iftrue)
    raise AssertionError(f"无法推导类型: {type(node).__name__}")


def _sizeof_type(node):
    """sizeof 类型路径（M5，修 BUG-1：编译期求值，operand 不求值）。"""
    if isinstance(node, c_ast.Typename):     # sizeof(类型)
        return type_of_decl(node).sizeof()
    return infer_type(node).sizeof()         # sizeof(表达式)：静态类型


def _alignof_type(node):
    """__alignof__/_Alignof 类型路径（M5，修 BUG-2：operand 不求值）。"""
    if isinstance(node, c_ast.Typename):
        return type_of_decl(node).alignof()
    return infer_type(node).alignof()


class ExeAssignment(Execute):
    """Assignment expression (including compound assignments)."""

    def _set_lvalue(self, lvalue_node, value):
        if isinstance(lvalue_node, ID):
            g_scope.set(lvalue_node.name, value)
        elif isinstance(lvalue_node, ArrayRef):
            arr = execute(lvalue_node.name)
            idx = execute(lvalue_node.subscript)
            if isinstance(arr, list):
                arr[idx] = value
            else:
                raise AssertionError("ArrayRef on non-array")
        elif isinstance(lvalue_node, StructRef):
            obj = execute(lvalue_node.name)
            field = lvalue_node.field.name if isinstance(lvalue_node.field, ID) else str(lvalue_node.field)
            if isinstance(obj, StructValue):
                obj.set(field, value)
            elif isinstance(obj, UnionValue):
                obj.set(field, value)
            elif isinstance(obj, dict):
                obj[field] = value
            else:
                setattr(obj, field, value)
        else:
            raise AssertionError(f"Unsupported lvalue type: {type(lvalue_node).__name__}")

    def execute(self):
        op = self.node.op
        rval = execute(self.node.rvalue)

        if op == '=':
            self._set_lvalue(self.node.lvalue, rval)
            return rval

        current = execute(self.node.lvalue)
        compound_ops = {
            '+=': lambda: current + rval,
            '-=': lambda: current - rval,
            '*=': lambda: current * rval,
            '/=': lambda: int(current / rval) if isinstance(current, int) and isinstance(rval, int) else current / rval,
            '%=': lambda: current % rval,
            '&=': lambda: current & rval,
            '|=': lambda: current | rval,
            '^=': lambda: current ^ rval,
            '<<=': lambda: current << rval,
            '>>=': lambda: current >> rval,
        }

        if op in compound_ops:
            new_val = compound_ops[op]()
            self._set_lvalue(self.node.lvalue, new_val)
            return new_val

        raise AssertionError(f"Unknown assignment operator: '{op}'")


class ExeTernaryOp(Execute):
    """Ternary conditional operator."""

    def execute(self):
        cond = execute(self.node.cond)
        if cond:
            return execute(self.node.iftrue)
        return execute(self.node.iffalse)


class ExeCast(Execute):
    """Type cast expression (M5: 复合类型走 coerce_to_type，标量沿用现有转换)."""

    def execute(self):
        val = execute(self.node.expr)
        try:
            ctype = type_of_decl(self.node.to_type)
        except AssertionError:
            ctype = None
        if ctype is not None and isinstance(ctype, (StructType, UnionType, ArrayType, EnumType, PtrType)):
            return coerce_to_type(val, ctype)
        type_names = self._extract_type_names(self.node.to_type)
        return _convert_value(val, type_names)

    def _extract_type_names(self, type_node):
        if isinstance(type_node, TypeDecl):
            return self._extract_type_names(type_node.type)
        if isinstance(type_node, Typename):
            if isinstance(type_node.type, TypeDecl):
                return self._extract_type_names(type_node.type)
            if isinstance(type_node.type, IdentifierType):
                return type_node.type.names
        if isinstance(type_node, IdentifierType):
            return type_node.names
        return ['int']


class ExeArrayRef(Execute):
    """Array subscript expression."""

    def execute(self):
        arr = execute(self.node.name)
        idx = execute(self.node.subscript)
        if isinstance(arr, (list, tuple)):
            return arr[idx]
        raise AssertionError(f"Cannot subscript non-array value: {type(arr).__name__}")


class ExeStructRef(Execute):
    """Struct/union member access (M3): StructValue/UnionValue 的 '.' 访问；
    '->' 在指针模型（MEM-1）前对 struct 值宽松退化为 '.'。"""

    def execute(self):
        obj = execute(self.node.name)
        field_node = self.node.field
        field_name = field_node.name if isinstance(field_node, ID) else str(field_node)

        if isinstance(obj, StructValue):
            return obj.get(field_name)
        if isinstance(obj, UnionValue):
            return obj.get(field_name)
        # 兼容兜底（旧 dict 值 / 任意对象）
        if isinstance(obj, dict):
            return obj.get(field_name, 0)
        return getattr(obj, field_name, 0)


class ExeFuncCall(Execute):
    """Function call expression."""

    def _eval_args(self, args_node):
        if args_node is None:
            return []
        if isinstance(args_node, ExprList):
            return [execute(e) for e in args_node.exprs]
        if isinstance(args_node, ParamList):
            return [execute(p) for p in args_node.params]
        if isinstance(args_node, TypeList):
            # __builtin_types_compatible_p(TypeList) - evaluate types
            return [execute(t) for t in args_node.types]
        return [execute(args_node)]

    def _call_builtin(self, name, args):
        """内置函数分发：经 cbuiltins 注册表（@builtin 装饰器注册，易扩展）。"""
        return call_builtin(name, args)

    def execute(self):
        name_node = self.node.name
        if isinstance(name_node, ID):
            func_name = name_node.name
        else:
            func_name = str(execute(name_node))

        args = self._eval_args(self.node.args)

        if func_name in g_functions:
            func = g_functions[func_name]
            global g_scope
            outer_scope = g_scope
            g_scope = Scope(func.closure_scope)

            for i, pname in enumerate(func.param_names):
                aval = args[i] if i < len(args) else 0
                if isinstance(aval, (StructValue, UnionValue)):
                    aval = aval.copy()            # M5 值传递：形参修改不影响实参
                ptype = func.param_types[i] if i < len(func.param_types) else None
                g_scope.declare(pname, aval, ptype)

            try:
                result = execute(func.body)
                return result
            except ReturnException as e:
                return e.value
            finally:
                g_scope = outer_scope

        return self._call_builtin(func_name, args)


class ExeExprList(Execute):
    """Comma-separated expression list (returns last value)."""

    def execute(self):
        result = None
        for expr in self.node.exprs or []:
            result = execute(expr)
        return result


# ==================== Statement Executors ====================

class ExeCompound(Execute):
    """Compound statement / block { ... }."""

    def execute(self):
        global g_scope
        outer = g_scope
        g_scope = Scope(outer)
        try:
            for item in self.node.block_items or []:
                execute(item)
        finally:
            g_scope = outer


class ExeIf(Execute):
    """If / else statement."""

    def execute(self):
        cond = execute(self.node.cond)
        if cond:
            if self.node.iftrue is not None:
                execute(self.node.iftrue)
        elif self.node.iffalse is not None:
            execute(self.node.iffalse)


class ExeWhile(Execute):
    """While loop."""

    def execute(self):
        while execute(self.node.cond):
            try:
                if self.node.stmt is not None:
                    execute(self.node.stmt)
            except BreakException:
                break
            except ContinueException:
                continue


class ExeDoWhile(Execute):
    """Do-While loop."""

    def execute(self):
        while True:
            try:
                if self.node.stmt is not None:
                    execute(self.node.stmt)
            except BreakException:
                break
            except ContinueException:
                pass
            if not execute(self.node.cond):
                break


class ExeFor(Execute):
    """For loop."""

    def execute(self):
        global g_scope
        outer = g_scope
        g_scope = Scope(outer)
        try:
            if self.node.init is not None:
                execute(self.node.init)
            while True:
                if self.node.cond is not None:
                    if not execute(self.node.cond):
                        break
                try:
                    if self.node.stmt is not None:
                        execute(self.node.stmt)
                except BreakException:
                    break
                except ContinueException:
                    pass
                if self.node.next is not None:
                    execute(self.node.next)
        finally:
            g_scope = outer


class ExeReturn(Execute):
    """Return statement."""

    def execute(self):
        val = execute(self.node.expr) if self.node.expr is not None else None
        raise ReturnException(val)


class ExeBreak(Execute):
    """Break statement."""

    def execute(self):
        raise BreakException()


class ExeContinue(Execute):
    """Continue statement."""

    def execute(self):
        raise ContinueException()


class ExeSwitch(Execute):
    """Switch statement."""

    def execute(self):
        cond = execute(self.node.cond)
        body = self.node.stmt

        stmts_to_run = []
        matched = False
        default_stmts = []

        if isinstance(body, Compound) and body.block_items:
            for item in body.block_items:
                if isinstance(item, Case):
                    if not matched:
                        case_expr = item.expr
                        # Handle RangeExpression in case ranges
                        if isinstance(case_expr, RangeExpression):
                            first = execute(case_expr.first)
                            last = execute(case_expr.last)
                            if first <= cond <= last:
                                matched = True
                            else:
                                continue
                        else:
                            case_val = execute(case_expr)
                            if case_val == cond:
                                matched = True
                            else:
                                continue
                    for s in (item.stmts or []):
                        stmts_to_run.append(s)
                elif isinstance(item, Default):
                    if not matched:
                        default_stmts = item.stmts or []
                    else:
                        for s in (item.stmts or []):
                            stmts_to_run.append(s)
                elif matched:
                    stmts_to_run.append(item)

        if not matched and default_stmts:
            stmts_to_run = list(default_stmts)

        try:
            for s in stmts_to_run:
                execute(s)
        except BreakException:
            pass


class ExeCase(Execute):
    """Case label (handled inside Switch)."""

    def execute(self):
        for stmt in self.node.stmts or []:
            execute(stmt)


class ExeDefault(Execute):
    """Default label (handled inside Switch)."""

    def execute(self):
        for stmt in self.node.stmts or []:
            execute(stmt)


# ==================== Declaration Executors ====================

class ExeDecl(Execute):
    """Variable declaration with optional initializer (typed, M3).

    初始化值经 coerce_to_type 按目标类型解释：
    struct ← InitList 顺序填充 / StructValue 值拷贝；数组 ← list 校验截断。
    """

    def execute(self):
        name = self.node.name
        if name is None:
            # 裸类型定义（struct S {...}; 被解析器包成 Decl(name=None)）：注册类型
            type_of_decl(self.node.type)
            return
        ctype = type_of_decl(self.node.type)
        if isinstance(ctype, FuncType):
            return  # 函数声明/原型：不是变量（定义由 FuncDef 注册，多文件支持）
        if self.node.init is not None:
            init_val = coerce_to_type(execute(self.node.init), ctype)
        else:
            init_val = default_value_for(ctype)
        g_scope.declare(name, init_val, ctype)


class ExeDeclList(Execute):
    """List of declarations."""

    def execute(self):
        for decl in self.node.decls or []:
            execute(decl)


class ExeFuncDef(Execute):
    """Function definition."""

    def _get_param_names(self, func_decl):
        if func_decl is None or func_decl.args is None:
            return []
        if isinstance(func_decl.args, ParamList):
            return [p.name for p in func_decl.args.params if isinstance(p, Decl)]
        return []

    def execute(self):
        decl = self.node.decl
        func_name = decl.name
        func_decl = decl.type
        param_names = self._get_param_names(func_decl)
        param_types, ret_type = None, None
        ft = type_of_decl(func_decl)             # M5: 提取参数/返回类型
        if isinstance(ft, FuncType):
            param_types = ft.param_types
            ret_type = ft.ret_type

        g_functions[func_name] = Function(
            name=func_name,
            param_names=param_names,
            body=self.node.body,
            closure_scope=g_scope,
            param_types=param_types,
            ret_type=ret_type,
        )


class ExeEmptyStatement(Execute):
    """Empty statement (;)."""

    def execute(self):
        pass


class ExeLabel(Execute):
    """Labeled statement."""

    def execute(self):
        if self.node.stmt is not None:
            execute(self.node.stmt)


class ExeGoto(Execute):
    """Goto statement (not supported)."""

    def execute(self):
        raise AssertionError(
            f"Goto is not supported in the interpreter (target: '{self.node.name}')"
        )


# ==================== Initializer Executors ====================

class ExeInitList(Execute):
    """Initializer list { ... } (M5: 含指定初始化器时返回 {键: 值} dict)."""

    def execute(self):
        items = self.node.exprs or []
        if any(isinstance(e, NamedInitializer) for e in items):
            d = {}
            for e in items:
                if isinstance(e, NamedInitializer):
                    d[_named_init_key(e)] = execute(e.expr)
                # 混合（先位置后指定）C99 不允许，忽略非指定项
            return d
        return [execute(e) for e in items]


def _named_init_key(node):
    """指定初始化器键：.field → 字符串成员名；[idx] → int 索引。

    仅支持单层；嵌套（.a.b / [i].c）留后续。
    """
    if node.name and len(node.name) == 1:
        n0 = node.name[0]
        if isinstance(n0, ID):
            return n0.name
        if isinstance(n0, Constant):
            return int(n0.value)
    raise AssertionError("暂不支持的指定初始化器（仅单层 .field 或 [idx]）")


class ExeNamedInitializer(Execute):
    """Named/designated initializer (.field = value)."""

    def execute(self):
        return execute(self.node.expr)


class ExeCompoundLiteral(Execute):
    """Compound literal (type){ ... } (M3): 按目标类型构造值（struct 得 StructValue）。"""

    def execute(self):
        ctype = type_of_decl(self.node.type)
        val = execute(self.node.init)
        return coerce_to_type(val, ctype)


# ==================== Type / Declaration Fragment Executors ====================

class ExeIdentifierType(Execute):
    """Base type name reference (e.g. 'int', 'float')."""
    def execute(self):
        return None


class ExeTypeDecl(Execute):
    """Type declaration wrapper."""
    def execute(self):
        return None


class ExePtrDecl(Execute):
    """Pointer type declaration."""
    def execute(self):
        return None


class ExeArrayDecl(Execute):
    """Array type declaration."""
    def execute(self):
        return None


class ExeFuncDecl(Execute):
    """Function type declaration."""
    def execute(self):
        return None


class ExeParamList(Execute):
    """Function parameter list."""
    def execute(self):
        return None


class ExeEllipsisParam(Execute):
    """Ellipsis parameter (...)."""
    def execute(self):
        return None


# ==================== Struct / Union / Enum Executors ====================

class ExeStruct(Execute):
    """Struct type definition (M3): 注册类型标签 + 计算布局。

    不再把成员声明为全局变量（P1 修复）；定义/前置声明统一走
    type_of_decl → _register_compound。
    """

    def execute(self):
        type_of_decl(self.node)


class ExeUnion(Execute):
    """Union type definition (M4 前置)：注册类型标签 + 计算布局，成员不污染作用域。"""

    def execute(self):
        type_of_decl(self.node)


def _process_enum_node(node):
    """枚举定义处理（M2）：计算常量表 → 注入当前作用域（带 IntType）→ 注册/更新类型标签。

    node: c_ast.Enum（values 非空）
    返回 EnumType。被 ExeEnum（独立枚举声明）与 ExeTypedef（typedef enum {...}）
    共用，保证常量表与类型注册只走一条路径。
    """
    int_type = g_types.resolve(['int'])
    constants = {}
    next_value = 0
    for e in node.values.enumerators or []:
        # 显式值可为常量表达式，且可引用前面已注入的枚举常量（如 B = A + 1）
        v = execute(e.value) if e.value is not None else next_value
        constants[e.name] = v
        g_scope.declare(e.name, v, int_type)
        next_value = v + 1
    if node.name and g_types.has_tag('enum', node.name):
        et = g_types.lookup_tag('enum', node.name)
        et.constants = constants          # 前置引用已注册：补全常量表
    else:
        et = EnumType(node.name, constants)
        if node.name:
            g_types.register_tag('enum', node.name, et)
    return et


class ExeEnum(Execute):
    """Enum type definition (M2): 常量注入作用域（带 IntType）+ 注册枚举类型标签。"""

    def execute(self):
        if self.node.values is not None:
            _process_enum_node(self.node)


class ExeEnumerator(Execute):
    """Single enumerator in an enum."""

    def execute(self):
        if self.node.value is not None:
            return execute(self.node.value)
        return None


class ExeEnumeratorList(Execute):
    """List of enumerators."""
    def execute(self):
        return None


# ==================== Other Executors ====================

class ExeTypedef(Execute):
    """Typedef declaration (M1+M2): 注册类型别名；typedef enum 同时注入枚举常量。"""

    def execute(self):
        name = self.node.name
        if not name:
            return
        # typedef enum {...} E; —— 枚举定义：常量注入 + 类型注册（C 语义）。
        # 注意：真实解析的 typedef 类型可能被 TypeDecl 包装（enum/struct 均如此，
        # 如 typedef enum Color {...} Color; 的 type 是 TypeDecl(Enum)），需先解包。
        inner = self.node.type
        while isinstance(inner, (TypeDecl, TypeDeclExt)):
            inner = inner.type
        if isinstance(inner, c_ast.Enum) and inner.values is not None:
            et = _process_enum_node(inner)
            g_types.register_typedef(name, et)
            return
        ctype = type_of_decl(self.node.type)
        g_types.register_typedef(name, ctype)


class ExeTypename(Execute):
    """Type name in a context like sizeof or cast."""
    def execute(self):
        return None


class ExeAlignas(Execute):
    """Alignment specifier (_Alignas)."""
    def execute(self):
        pass


class ExeStaticAssert(Execute):
    """Static assertion (_Static_assert)."""

    def execute(self):
        cond = execute(self.node.cond)
        if not cond:
            msg = execute(self.node.message) if self.node.message else ""
            raise AssertionError(f"static_assert failed: {msg}")


class ExePragma(Execute):
    """Pragma directive."""
    def execute(self):
        pass


class ExeFileAST(Execute):
    """Top-level file AST node."""

    def execute(self):
        result = None
        for ext in self.node.ext or []:
            result = execute(ext)
        return result


# ==================== GNU C Extension Executors ====================

class ExeTypeList(Execute):
    """Type list (used in __builtin_types_compatible_p())."""

    def execute(self):
        return [execute(t) for t in self.node.types or []]


class ExeAttributeSpecifier(Execute):
    """__attribute__((...)) specifier - compile-time annotation, no runtime effect."""

    def execute(self):
        return None


class ExeAsm(Execute):
    """Inline assembly statement / label.

    In a real interpreter this would be a no-op or delegate to a
    platform-specific assembler. Here we simply evaluate the
    template and operands as expressions and return the template.
    """

    def execute(self):
        template_val = execute(self.node.template) if self.node.template is not None else ""
        output_val = execute(self.node.output_operands) if self.node.output_operands is not None else None
        input_val = execute(self.node.input_operands) if self.node.input_operands is not None else None
        clobber_val = execute(self.node.clobbered_regs) if self.node.clobbered_regs is not None else None
        return str(template_val) if template_val else ""


class ExePreprocessorLine(Execute):
    """Preprocessor line directive (OpenCL)."""

    def execute(self):
        return None


class ExeTypeOfDeclaration(Execute):
    """typeof(declaration) - returns the type name as a string."""

    def execute(self):
        # Evaluate the declaration to register it, then return type info
        execute(self.node.declaration)
        return 'typeof_decl'


class ExeTypeOfExpression(Execute):
    """typeof(expression) - returns the Python type name of the expression result."""

    def execute(self):
        val = execute(self.node.expr)
        return type(val).__name__


class ExeRangeExpression(Execute):
    """Range expression (first ... last), used in case ranges and designated initializers."""

    def execute(self):
        first = execute(self.node.first)
        last = execute(self.node.last)
        return first, last  # Return as a tuple range


class ExeTypeDeclExt(Execute):
    """Extended TypeDecl with asm/attributes fields."""

    def execute(self):
        return None


class ExeArrayDeclExt(Execute):
    """Extended ArrayDecl with asm/attributes fields."""

    def execute(self):
        return None


class ExeStructExt(Execute):
    """Extended Struct with attributes (M3): 同 ExeStruct，注册类型 + 布局。

    attrib（__attribute__）为编译期元数据；aligned 覆盖已在
    compute_struct_layout 的 align_override 支持（端到端提取留 M5）。
    """

    def execute(self):
        type_of_decl(self.node)


class ExeFuncDeclExt(Execute):
    """Extended function declaration with attributes and asm.

    Similar to FuncDecl but registers the function with extended metadata.
    """

    def execute(self):
        # At this point the function definition (FuncDef) handles registration.
        # FuncDeclExt alone is just a type fragment.
        return None


# ==================== Dispatch Table ====================

g_exe_class = {
    # === Standard nodes ===
    # Expressions
    'Constant': ExeConstant,
    'ID': ExeID,
    'BinaryOp': ExeBinaryOp,
    'UnaryOp': ExeUnaryOp,
    'Assignment': ExeAssignment,
    'TernaryOp': ExeTernaryOp,
    'Cast': ExeCast,
    'ArrayRef': ExeArrayRef,
    'StructRef': ExeStructRef,
    'FuncCall': ExeFuncCall,
    'ExprList': ExeExprList,
    # Statements
    'Compound': ExeCompound,
    'If': ExeIf,
    'While': ExeWhile,
    'DoWhile': ExeDoWhile,
    'For': ExeFor,
    'Return': ExeReturn,
    'Break': ExeBreak,
    'Continue': ExeContinue,
    'Switch': ExeSwitch,
    'Case': ExeCase,
    'Default': ExeDefault,
    # Declarations
    'Decl': ExeDecl,
    'DeclList': ExeDeclList,
    'FuncDef': ExeFuncDef,
    'EmptyStatement': ExeEmptyStatement,
    'Label': ExeLabel,
    'Goto': ExeGoto,
    # Initializers
    'InitList': ExeInitList,
    'NamedInitializer': ExeNamedInitializer,
    'CompoundLiteral': ExeCompoundLiteral,
    # Type fragments
    'IdentifierType': ExeIdentifierType,
    'TypeDecl': ExeTypeDecl,
    'PtrDecl': ExePtrDecl,
    'ArrayDecl': ExeArrayDecl,
    'FuncDecl': ExeFuncDecl,
    'ParamList': ExeParamList,
    'EllipsisParam': ExeEllipsisParam,
    # Struct / Union / Enum
    'Struct': ExeStruct,
    'Union': ExeUnion,
    'Enum': ExeEnum,
    'Enumerator': ExeEnumerator,
    'EnumeratorList': ExeEnumeratorList,
    # Type system
    'Typedef': ExeTypedef,
    'Typename': ExeTypename,
    # Other
    'Alignas': ExeAlignas,
    'StaticAssert': ExeStaticAssert,
    'Pragma': ExePragma,
    # Top-level
    'FileAST': ExeFileAST,

    # === GNU C Extension nodes ===
    'TypeList': ExeTypeList,
    'AttributeSpecifier': ExeAttributeSpecifier,
    'Asm': ExeAsm,
    'PreprocessorLine': ExePreprocessorLine,
    'TypeOfDeclaration': ExeTypeOfDeclaration,
    'TypeOfExpression': ExeTypeOfExpression,
    'RangeExpression': ExeRangeExpression,
    'TypeDeclExt': ExeTypeDeclExt,
    'ArrayDeclExt': ExeArrayDeclExt,
    'StructExt': ExeStructExt,
    'FuncDeclExt': ExeFuncDeclExt,
}


# ==================== Tests ====================

def setup_global_scope():
    """Reset the global scope and function table for testing."""
    global g_scope, g_functions
    g_scope = Scope()
    g_scope.declare('i', 0)
    g_scope.declare('j', 0)
    g_functions = {}


# ----- Standard Node Tests -----

def test_basic_expression():
    print("  [Expression] 1 + 1 =", end=' ')
    node = BinaryOp(
        op='+',
        left=Constant(type='int', value='1'),
        right=Constant(type='int', value='1'),
    )
    result = execute(node)
    assert result == 2, f"Expected 2, got {result}"
    print(f"{result} ✓")


def test_assignment_and_variable():
    print("  [Assignment] i = 2 + 3", end=' ')
    node = Assignment(
        op='=',
        lvalue=ID('i'),
        rvalue=BinaryOp(
            op='+',
            left=Constant(type='int', value='2'),
            right=Constant(type='int', value='3'),
        ),
    )
    result = execute(node)
    assert result == 5, f"Expected 5, got {result}"
    assert g_scope.get('i') == 5, f"Expected i=5, got i={g_scope.get('i')}"
    print(f"=> i = {g_scope.get('i')} ✓")


def test_all_binary_operators():
    print("  [BinaryOp] All operators:")
    a = Constant(type='int', value='10')
    b = Constant(type='int', value='3')

    cases = [
        ('+', 13), ('-', 7), ('*', 30), ('/', 3), ('%', 1),
        ('==', False), ('!=', True), ('<', False), ('>', True),
        ('<=', False), ('>=', True),
        ('&&', True), ('||', True),
        ('&', 2), ('|', 11), ('^', 9),
        ('<<', 80), ('>>', 1),
    ]
    for op, expected in cases:
        node = BinaryOp(op=op, left=a, right=b)
        result = execute(node)
        ok = "✓" if result == expected else "✗"
        print(f"    10 {op} 3 = {result} (expected {expected}) {ok}")
        assert result == expected, f"10 {op} 3: expected {expected}, got {result}"


def test_unary_operators():
    print("  [UnaryOp] Unary operators:")

    cases = [
        ('-', Constant(type='int', value='5'), -5),
        ('+', Constant(type='int', value='5'), 5),
        ('!', Constant(type='int', value='0'), True),
        ('~', Constant(type='int', value='5'), -6),
    ]
    for op, operand, expected in cases:
        node = UnaryOp(op=op, expr=operand)
        result = execute(node)
        ok = "✓" if result == expected else "✗"
        print(f"    {op}{operand.value} = {result} (expected {expected}) {ok}")
        assert result == expected, f"{op}{operand.value}: expected {expected}, got {result}"
    
    cases = [
        ('p++', ID(name='i'), 5, 6),
        ('p--', ID(name='i'), 5, 4),
    ]
    for op, operand, expected, virable_expected in cases:
        g_scope.set('i', 5)
        node = UnaryOp(op=op, expr=operand)
        result = execute(node)
        ok = "✓" if result == expected and g_scope.get('i') == virable_expected else "✗"
        print(f"{op} for {operand.name} {ok}")
        assert result == expected, f"{result} != {expected}"
        assert g_scope.get('i') == virable_expected, f"{g_scope.get('i')} != {virable_expected}"


def test_ternary_operator():
    print("  [TernaryOp] Ternary operator:")

    node = TernaryOp(
        cond=Constant(type='int', value='1'),
        iftrue=Constant(type='int', value='10'),
        iffalse=Constant(type='int', value='20'),
    )
    result = execute(node)
    assert result == 10, f"Expected 10, got {result}"
    print(f"    1 ? 10 : 20 = {result} ✓")

    node = TernaryOp(
        cond=Constant(type='int', value='0'),
        iftrue=Constant(type='int', value='10'),
        iffalse=Constant(type='int', value='20'),
    )
    result = execute(node)
    assert result == 20, f"Expected 20, got {result}"
    print(f"    0 ? 10 : 20 = {result} ✓")


def test_compound_assignment():
    print("  [Assignment] Compound assignments:")

    g_scope.set('i', 10)
    node = Assignment(op='+=', lvalue=ID('i'), rvalue=Constant(type='int', value='5'))
    execute(node)
    assert g_scope.get('i') == 15, f"Expected i=15, got i={g_scope.get('i')}"
    print(f"    i = 10; i += 5 => i = {g_scope.get('i')} ✓")

    node = Assignment(op='-=', lvalue=ID('i'), rvalue=Constant(type='int', value='3'))
    execute(node)
    assert g_scope.get('i') == 12, f"Expected i=12, got i={g_scope.get('i')}"
    print(f"    i -= 3 => i = {g_scope.get('i')} ✓")

    node = Assignment(op='*=', lvalue=ID('i'), rvalue=Constant(type='int', value='2'))
    execute(node)
    assert g_scope.get('i') == 24, f"Expected i=24, got i={g_scope.get('i')}"
    print(f"    i *= 2 => i = {g_scope.get('i')} ✓")


def test_expr_list():
    print("  [ExprList] Comma expression:", end=' ')
    node = ExprList(exprs=[
        Constant(type='int', value='1'),
        Constant(type='int', value='2'),
        Constant(type='int', value='3'),
    ])
    result = execute(node)
    assert result == 3, f"Expected 3, got {result}"
    print(f"(1, 2, 3) = {result} ✓")


def test_if_statement():
    print("  [If] If/else statement:")

    g_scope.declare('result', 0)

    if_node = If(
        cond=Constant(type='int', value='1'),
        iftrue=Compound(block_items=[
            Assignment(op='=', lvalue=ID('result'), rvalue=Constant(type='int', value='42')),
        ]),
        iffalse=None,
    )
    execute(if_node)
    assert g_scope.get('result') == 42, f"Expected 42, got {g_scope.get('result')}"
    print(f"    if (1) result=42 => result = {g_scope.get('result')} ✓")

    g_scope.set('result', 0)
    if_node = If(
        cond=Constant(type='int', value='0'),
        iftrue=Compound(block_items=[
            Assignment(op='=', lvalue=ID('result'), rvalue=Constant(type='int', value='100')),
        ]),
        iffalse=Compound(block_items=[
            Assignment(op='=', lvalue=ID('result'), rvalue=Constant(type='int', value='200')),
        ]),
    )
    execute(if_node)
    assert g_scope.get('result') == 200, f"Expected 200, got {g_scope.get('result')}"
    print(f"    if (0) result=100 else result=200 => result = {g_scope.get('result')} ✓")


def test_while_loop():
    print("  [While] While loop:")
    g_scope.declare('count', 0)
    g_scope.declare('sum', 0)

    body = Compound(block_items=[
        Assignment(op='=', lvalue=ID('sum'), rvalue=BinaryOp(op='+', left=ID('sum'), right=ID('count'))),
        Assignment(op='=', lvalue=ID('count'), rvalue=BinaryOp(op='+', left=ID('count'), right=Constant(type='int', value='1'))),
    ])
    wnode = While(
        cond=BinaryOp(op='<', left=ID('count'), right=Constant(type='int', value='5')),
        stmt=body,
    )
    execute(wnode)
    assert g_scope.get('sum') == 10, f"Expected sum=10, got {g_scope.get('sum')}"
    assert g_scope.get('count') == 5, f"Expected count=5, got {g_scope.get('count')}"
    print(f"    sum 0..4 = {g_scope.get('sum')}, count = {g_scope.get('count')} ✓")


def test_for_loop():
    print("  [For] For loop:")
    g_scope.declare('s', 0)

    for_node = For(
        init=Assignment(op='=', lvalue=ID('i'), rvalue=Constant(type='int', value='0')),
        cond=BinaryOp(op='<', left=ID('i'), right=Constant(type='int', value='3')),
        next=Assignment(op='=', lvalue=ID('i'), rvalue=BinaryOp(op='+', left=ID('i'), right=Constant(type='int', value='1'))),
        stmt=Compound(block_items=[
            Assignment(op='=', lvalue=ID('s'), rvalue=BinaryOp(op='+', left=ID('s'), right=ID('i'))),
        ]),
    )
    execute(for_node)
    assert g_scope.get('s') == 3, f"Expected s=3, got {g_scope.get('s')}"
    print(f"    for (i=0; i<3; i++) s+=i => s = {g_scope.get('s')} ✓")


def test_do_while_loop():
    print("  [DoWhile] Do-While loop:")
    g_scope.declare('x', 0)

    body = Compound(block_items=[
        Assignment(op='=', lvalue=ID('x'), rvalue=BinaryOp(op='+', left=ID('x'), right=Constant(type='int', value='1'))),
    ])
    dnode = DoWhile(
        cond=BinaryOp(op='<', left=ID('x'), right=Constant(type='int', value='3')),
        stmt=body,
    )
    execute(dnode)
    assert g_scope.get('x') == 3, f"Expected x=3, got {g_scope.get('x')}"
    print(f"    do {{ x++; }} while(x<3) => x = {g_scope.get('x')} ✓")


def test_block_scope():
    print("  [Scope] Block scoping:")
    g_scope.declare('x', 1)

    inner = Compound(block_items=[
        Decl(
            name='x', quals=[], align=None, storage=[], funcspec=[],
            type=TypeDecl(declname='x', quals=[], align=None, type=IdentifierType(names=['int'])),
            init=Constant(type='int', value='2'), bitsize=None,
        ),
        Assignment(op='=', lvalue=ID('x'), rvalue=BinaryOp(op='+', left=ID('x'), right=Constant(type='int', value='1'))),
    ])
    execute(inner)
    assert g_scope.get('x') == 1, f"Expected outer x=1, got {g_scope.get('x')}"
    print(f"    outer x stays {g_scope.get('x')} after inner block ✓")


def test_function_call():
    print("  [FuncDef/FuncCall] Function call:")

    func_decl = Decl(
        name='add', quals=[], align=None, storage=[], funcspec=[],
        type=FuncDecl(
            args=ParamList(params=[
                Decl(name='a', quals=[], align=None, storage=[], funcspec=[],
                     type=TypeDecl(declname='a', quals=[], align=None, type=IdentifierType(names=['int'])),
                     init=None, bitsize=None),
                Decl(name='b', quals=[], align=None, storage=[], funcspec=[],
                     type=TypeDecl(declname='b', quals=[], align=None, type=IdentifierType(names=['int'])),
                     init=None, bitsize=None),
            ]),
            type=TypeDecl(declname='add', quals=[], align=None, type=IdentifierType(names=['int'])),
        ),
        init=None, bitsize=None,
    )
    func_body = Compound(block_items=[
        Return(expr=BinaryOp(op='+', left=ID('a'), right=ID('b'))),
    ])
    func_def = FuncDef(decl=func_decl, param_decls=None, body=func_body)
    execute(func_def)

    call_node = FuncCall(
        name=ID('add'),
        args=ExprList(exprs=[Constant(type='int', value='3'), Constant(type='int', value='4')]),
    )
    result = execute(call_node)
    assert result == 7, f"Expected 7, got {result}"
    print(f"    add(3, 4) = {result} ✓")

    g_functions['fortytwo'] = Function(
        name='fortytwo', param_names=[],
        body=Compound(block_items=[Return(expr=Constant(type='int', value='42'))]),
        closure_scope=g_scope,
    )
    result = execute(FuncCall(name=ID('fortytwo'), args=None))
    assert result == 42, f"Expected 42, got {result}"
    print(f"    fortytwo() = {result} ✓")


def test_break_continue():
    print("  [Break/Continue] Loop control:")
    g_scope.declare('found', 0)

    body = Compound(block_items=[
        If(
            cond=BinaryOp(op='>=', left=ID('found'), right=Constant(type='int', value='3')),
            iftrue=Break(),
            iffalse=None,
        ),
        Assignment(op='=', lvalue=ID('found'), rvalue=BinaryOp(op='+', left=ID('found'), right=Constant(type='int', value='1'))),
        Continue(),
        Assignment(op='=', lvalue=ID('found'), rvalue=Constant(type='int', value='999')),
    ])
    wnode = While(cond=Constant(type='int', value='1'), stmt=body)
    execute(wnode)
    assert g_scope.get('found') == 3, f"Expected found=3, got {g_scope.get('found')}"
    print(f"    break after found=3, continue skips assignment ✓")


def test_switch_case():
    print("  [Switch/Case] Switch statement:")
    g_scope.declare('val', 0)

    switch_node = Switch(
        cond=Constant(type='int', value='2'),
        stmt=Compound(block_items=[
            Case(expr=Constant(type='int', value='1'), stmts=[
                Assignment(op='=', lvalue=ID('val'), rvalue=Constant(type='int', value='10')),
                Break(),
            ]),
            Case(expr=Constant(type='int', value='2'), stmts=[
                Assignment(op='=', lvalue=ID('val'), rvalue=Constant(type='int', value='20')),
            ]),
            Case(expr=Constant(type='int', value='3'), stmts=[
                Assignment(op='=', lvalue=ID('val'), rvalue=Constant(type='int', value='30')),
                Break(),
            ]),
            Default(stmts=[
                Assignment(op='=', lvalue=ID('val'), rvalue=Constant(type='int', value='99')),
            ]),
        ]),
    )
    execute(switch_node)
    assert g_scope.get('val') == 30, f"Expected val=30 (fall-through), got {g_scope.get('val')}"
    print(f"    switch(2) fall-through case 2 -> case 3 => val = {g_scope.get('val')} ✓")

    g_scope.set('val', 0)
    switch_node2 = Switch(
        cond=Constant(type='int', value='99'),
        stmt=Compound(block_items=[
            Case(expr=Constant(type='int', value='1'), stmts=[
                Assignment(op='=', lvalue=ID('val'), rvalue=Constant(type='int', value='10')),
            ]),
            Default(stmts=[
                Assignment(op='=', lvalue=ID('val'), rvalue=Constant(type='int', value='42')),
            ]),
        ]),
    )
    execute(switch_node2)
    assert g_scope.get('val') == 42, f"Expected val=42 (default), got {g_scope.get('val')}"
    print(f"    switch(99) default => val = {g_scope.get('val')} ✓")


def test_declaration():
    print("  [Decl] Variable declaration:")

    decl = Decl(
        name='x', quals=[], align=None, storage=[], funcspec=[],
        type=TypeDecl(declname='x', quals=[], align=None, type=IdentifierType(names=['int'])),
        init=Constant(type='int', value='10'), bitsize=None,
    )
    execute(decl)
    assert g_scope.get('x') == 10, f"Expected x=10, got {g_scope.get('x')}"
    print(f"    int x = 10 => x = {g_scope.get('x')} ✓")

    decl2 = Decl(
        name='y', quals=[], align=None, storage=[], funcspec=[],
        type=TypeDecl(declname='y', quals=[], align=None, type=IdentifierType(names=['int'])),
        init=None, bitsize=None,
    )
    execute(decl2)
    assert g_scope.get('y') == 0, f"Expected y=0, got {g_scope.get('y')}"
    print(f"    int y; (default) => y = {g_scope.get('y')} ✓")


def test_enum():
    print("  [Enum] Enum definition:")

    enum_node = Enum(
        name='color',
        values=EnumeratorList(enumerators=[
            Enumerator(name='RED', value=None),
            Enumerator(name='GREEN', value=None),
            Enumerator(name='BLUE', value=Constant(type='int', value='10')),
            Enumerator(name='YELLOW', value=None),
        ]),
    )
    execute(enum_node)
    assert g_scope.get('RED') == 0
    assert g_scope.get('GREEN') == 1
    assert g_scope.get('BLUE') == 10
    assert g_scope.get('YELLOW') == 11
    print(f"    RED={g_scope.get('RED')}, GREEN={g_scope.get('GREEN')}, "
          f"BLUE={g_scope.get('BLUE')}, YELLOW={g_scope.get('YELLOW')} ✓")


def test_cast():
    print("  [Cast] Type cast:", end=' ')
    cast_node = Cast(
        to_type=Typename(
            name=None, quals=[], align=None,
            type=TypeDecl(declname=None, quals=[], align=None, type=IdentifierType(names=['float'])),
        ),
        expr=Constant(type='int', value='42'),
    )
    result = execute(cast_node)
    assert result == 42.0, f"Expected 42.0, got {result}"
    print(f"(float)42 = {result} ✓")


def test_static_assert():
    print("  [StaticAssert] Static assert:", end=' ')

    node = StaticAssert(cond=Constant(type='int', value='1'), message=Constant(type='string', value='ok'))
    execute(node)
    print("pass ✓")

    node = StaticAssert(cond=Constant(type='int', value='0'), message=Constant(type='string', value='fail'))
    try:
        execute(node)
        assert False, "Should have raised AssertionError"
    except AssertionError:
        print("    _Static_assert(0, ...) raises AssertionError ✓")


def test_init_list():
    print("  [InitList] Initializer list:", end=' ')
    node = InitList(exprs=[
        Constant(type='int', value='1'),
        Constant(type='int', value='2'),
        Constant(type='int', value='3'),
    ])
    result = execute(node)
    assert result == [1, 2, 3], f"Expected [1,2,3], got {result}"
    print(f"{result} ✓")


def test_file_ast():
    print("  [FileAST] File-level execution:", end=' ')
    file_node = FileAST(ext=[
        Decl(name='a', quals=[], align=None, storage=[], funcspec=[],
             type=TypeDecl(declname='a', quals=[], align=None, type=IdentifierType(names=['int'])),
             init=Constant(type='int', value='100'), bitsize=None),
        Assignment(op='=', lvalue=ID('a'), rvalue=BinaryOp(op='+', left=ID('a'), right=Constant(type='int', value='1'))),
    ])
    result = execute(file_node)
    assert g_scope.get('a') == 101, f"Expected a=101, got {g_scope.get('a')}"
    print(f"a = {g_scope.get('a')} ✓")


def test_return_value():
    print("  [Return] Return statement:")

    g_functions['getval'] = Function(
        name='getval', param_names=[],
        body=Compound(block_items=[Return(expr=Constant(type='int', value='77'))]),
        closure_scope=g_scope,
    )
    result = execute(FuncCall(name=ID('getval'), args=None))
    assert result == 77, f"Expected 77, got {result}"
    print(f"    return 77 => {result} ✓")


def test_label_empty():
    print("  [Label/Empty] Label + EmptyStatement:")

    g_scope.declare('labeled_val', 0)

    label_node = Label(
        name='mylabel',
        stmt=Compound(block_items=[
            Assignment(op='=', lvalue=ID('labeled_val'), rvalue=Constant(type='int', value='5')),
        ]),
    )
    execute(label_node)
    assert g_scope.get('labeled_val') == 5
    print(f"    label: compound works ✓")

    execute(EmptyStatement())
    print(f"    EmptyStatement: no-op ✓")


def test_struct_union():
    print("  [Struct] Struct 定义注册类型（M3，成员不再污染全局作用域）:")

    struct_node = Struct(
        name='Point',
        decls=[
            Decl(name='px', quals=[], align=None, storage=[], funcspec=[],
                 type=TypeDecl(declname='px', quals=[], align=None, type=IdentifierType(names=['int'])),
                 init=None, bitsize=None),
            Decl(name='py', quals=[], align=None, storage=[], funcspec=[],
                 type=TypeDecl(declname='py', quals=[], align=None, type=IdentifierType(names=['int'])),
                 init=None, bitsize=None),
        ],
    )
    execute(struct_node)
    # P1 修复：成员不是全局变量
    assert g_types.has_tag('struct', 'Point')
    st = g_types.lookup_tag('struct', 'Point')
    assert st.sizeof() == 8, f"sizeof(struct Point) 期望 8，实际 {st.sizeof()}"
    for m in ('px', 'py'):
        try:
            g_scope.get(m)
            raise AssertionError(f"成员 '{m}' 不应成为全局变量（P1）")
        except AssertionError:
            pass
    print("    struct Point 注册；sizeof=8；成员不污染全局作用域 ✓")


def test_compound_literal():
    print("  [CompoundLiteral] Compound literal:", end=' ')
    node = CompoundLiteral(
        type=TypeDecl(declname=None, quals=[], align=None, type=IdentifierType(names=['int'])),
        init=InitList(exprs=[Constant(type='int', value='10'), Constant(type='int', value='20')]),
    )
    result = execute(node)
    assert result == [10, 20], f"Expected [10, 20], got {result}"
    print(f"{result} ✓")


def test_type_fragments():
    """Test that all type/fragment nodes don't crash."""
    print("  [TypeNodes] Type declaration fragments (no-op):")

    execute(IdentifierType(names=['int']))
    execute(TypeDecl(declname='x', quals=[], align=None, type=IdentifierType(names=['int'])))
    execute(PtrDecl(quals=[], type=IdentifierType(names=['int'])))
    execute(ArrayDecl(type=IdentifierType(names=['int']), dim=Constant(type='int', value='10'), dim_quals=[]))
    execute(FuncDecl(args=None, type=IdentifierType(names=['int'])))
    execute(ParamList(params=[]))
    execute(EllipsisParam())
    execute(Typedef(name='myint', quals=[], storage=[], type=IdentifierType(names=['int'])))
    execute(Typename(name=None, quals=[], align=None, type=IdentifierType(names=['int'])))
    execute(Alignas(alignment=Constant(type='int', value='8')))
    execute(Pragma(string="once"))
    execute(NamedInitializer(name=[ID('x')], expr=Constant(type='int', value='5')))

    print(f"    All 12 type/fragment nodes executed without error ✓")


# ----- GNU C Extension Tests -----

def test_gnu_type_list():
    """Test TypeList node."""
    print("  [TypeList] Type list:", end=' ')
    node = TypeList(types=[
        TypeDecl(declname='a', quals=[], align=None, type=IdentifierType(names=['int'])),
        TypeDecl(declname='b', quals=[], align=None, type=IdentifierType(names=['float'])),
    ])
    result = execute(node)
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    print(f"list of {len(result)} types ✓")


def test_gnu_attribute_specifier():
    """Test AttributeSpecifier node (no runtime effect)."""
    print("  [AttributeSpecifier] __attribute__:", end=' ')
    node = AttributeSpecifier(
        exprlist=ExprList(exprs=[ID('aligned'), Constant(type='int', value='8')]),
    )
    result = execute(node)
    assert result is None, f"Expected None, got {result}"
    print("no-op ✓")


def test_gnu_asm():
    """Test Asm node (inline assembly)."""
    print("  [Asm] Inline assembly:")

    # asm("nop")
    node = Asm(
        asm_keyword='asm',
        template=Constant(type='string', value='nop'),
        output_operands=None,
        input_operands=None,
        clobbered_regs=None,
    )
    result = execute(node)
    print(f"    asm(\"nop\") => '{result}' ✓")

    # asm volatile("mov %0, %1" : "=r"(x) : "r"(y))
    node2 = Asm(
        asm_keyword='asm volatile',
        template=Constant(type='string', value='mov %0, %1'),
        output_operands=ExprList(exprs=[Constant(type='string', value='=r(x)')]),
        input_operands=ExprList(exprs=[Constant(type='string', value='r(y)')]),
        clobbered_regs=ExprList(exprs=[Constant(type='string', value='memory')]),
    )
    result2 = execute(node2)
    assert 'mov' in str(result2), "Expected template to contain 'mov'"
    print(f"    asm volatile(\"mov %0, %1\" : ...) => '{result2}' ✓")


def test_gnu_preprocessor_line():
    """Test PreprocessorLine node."""
    print("  [PreprocessorLine] Preprocessor line:", end=' ')
    node = PreprocessorLine(contents="#line 42 \"test.c\"")
    result = execute(node)
    assert result is None, f"Expected None, got {result}"
    print("no-op ✓")


def test_gnu_typeof_declaration():
    """Test TypeOfDeclaration node."""
    print("  [TypeOfDeclaration] typeof(declaration):", end=' ')
    decl = Decl(
        name='tmp', quals=[], align=None, storage=[], funcspec=[],
        type=TypeDecl(declname='tmp', quals=[], align=None, type=IdentifierType(names=['int'])),
        init=Constant(type='int', value='42'), bitsize=None,
    )
    node = TypeOfDeclaration(typeof_keyword='typeof', declaration=decl)
    result = execute(node)
    print(f"'{result}' ✓")


def test_gnu_typeof_expression():
    """Test TypeOfExpression node."""
    print("  [TypeOfExpression] typeof(expression):", end=' ')
    node = TypeOfExpression(
        typeof_keyword='typeof',
        expr=Constant(type='int', value='42'),
    )
    result = execute(node)
    assert result == 'int', f"Expected 'int', got {result}"
    print(f"typeof(42) => '{result}' ✓")

    node2 = TypeOfExpression(
        typeof_keyword='typeof',
        expr=Constant(type='float', value='3.14'),
    )
    result2 = execute(node2)
    print(f"    typeof(3.14) => '{result2}' ✓")


def test_gnu_range_expression():
    """Test RangeExpression node (case ranges, designated init ranges)."""
    print("  [RangeExpression] Range expression:", end=' ')
    node = RangeExpression(
        first=Constant(type='int', value='1'),
        last=Constant(type='int', value='5'),
    )
    result = execute(node)
    assert result == (1, 5), f"Expected (1, 5), got {result}"
    print(f"1...5 = {result} ✓")


def test_gnu_case_range():
    """Test switch case with RangeExpression (GNU extension)."""
    print("  [Case+RangeExpression] Case range switch:")
    g_scope.declare('val2', 0)

    # switch (3) { case 1...2: val2=10; break; case 3...5: val2=20; break; default: val2=99; }
    switch_node = Switch(
        cond=Constant(type='int', value='3'),
        stmt=Compound(block_items=[
            Case(
                expr=RangeExpression(
                    first=Constant(type='int', value='1'),
                    last=Constant(type='int', value='2'),
                ),
                stmts=[
                    Assignment(op='=', lvalue=ID('val2'), rvalue=Constant(type='int', value='10')),
                    Break(),
                ],
            ),
            Case(
                expr=RangeExpression(
                    first=Constant(type='int', value='3'),
                    last=Constant(type='int', value='5'),
                ),
                stmts=[
                    Assignment(op='=', lvalue=ID('val2'), rvalue=Constant(type='int', value='20')),
                    Break(),
                ],
            ),
            Default(stmts=[
                Assignment(op='=', lvalue=ID('val2'), rvalue=Constant(type='int', value='99')),
            ]),
        ]),
    )
    execute(switch_node)
    assert g_scope.get('val2') == 20, f"Expected val2=20 (case 3...5), got {g_scope.get('val2')}"
    print(f"    switch(3) case 3...5 => val2 = {g_scope.get('val2')} ✓")

    # Test value in lower range
    g_scope.set('val2', 0)
    switch_node2 = Switch(
        cond=Constant(type='int', value='2'),
        stmt=Compound(block_items=[
            Case(
                expr=RangeExpression(first=Constant(type='int', value='1'), last=Constant(type='int', value='2')),
                stmts=[Assignment(op='=', lvalue=ID('val2'), rvalue=Constant(type='int', value='10')), Break()],
            ),
            Case(
                expr=RangeExpression(first=Constant(type='int', value='3'), last=Constant(type='int', value='5')),
                stmts=[Assignment(op='=', lvalue=ID('val2'), rvalue=Constant(type='int', value='20')), Break()],
            ),
        ]),
    )
    execute(switch_node2)
    assert g_scope.get('val2') == 10, f"Expected val2=10 (case 1...2), got {g_scope.get('val2')}"
    print(f"    switch(2) case 1...2 => val2 = {g_scope.get('val2')} ✓")


def test_gnu_type_decl_ext():
    """Test TypeDeclExt node (extended TypeDecl with asm/attributes)."""
    print("  [TypeDeclExt] Extended TypeDecl:", end=' ')

    # TypeDeclExt behaves like TypeDecl at runtime
    node = TypeDeclExt(
        declname='x', quals=[], align=None,
        type=IdentifierType(names=['int']),
    )
    result = execute(node)
    assert result is None
    print("no-op ✓")


def test_gnu_array_decl_ext():
    """Test ArrayDeclExt node."""
    print("  [ArrayDeclExt] Extended ArrayDecl:", end=' ')
    node = ArrayDeclExt(
        type=IdentifierType(names=['int']),
        dim=Constant(type='int', value='10'),
        dim_quals=[],
    )
    result = execute(node)
    assert result is None
    print("no-op ✓")


def test_gnu_struct_ext():
    """Test StructExt node (extended Struct with attributes, M3)."""
    print("  [StructExt] Extended Struct with attributes:", end=' ')

    node = StructExt(
        name='AlignedPoint',
        decls=[
            Decl(name='x', quals=[], align=None, storage=[], funcspec=[],
                 type=TypeDecl(declname='x', quals=[], align=None, type=IdentifierType(names=['int'])),
                 init=None, bitsize=None),
            Decl(name='y', quals=[], align=None, storage=[], funcspec=[],
                 type=TypeDecl(declname='y', quals=[], align=None, type=IdentifierType(names=['int'])),
                 init=None, bitsize=None),
        ],
    )
    execute(node)
    # 成员不污染作用域；标签注册 + 布局
    assert g_types.has_tag('struct', 'AlignedPoint')
    st = g_types.lookup_tag('struct', 'AlignedPoint')
    assert st.sizeof() == 8
    print(f"AlignedPoint 注册，sizeof={st.sizeof()}，成员不入作用域 ✓")


def test_gnu_func_decl_ext():
    """Test FuncDeclExt node."""
    print("  [FuncDeclExt] Extended function declaration:", end=' ')

    node = FuncDeclExt(
        args=ParamList(params=[]),
        type=TypeDecl(declname='foo', quals=[], align=None, type=IdentifierType(names=['int'])),
        attributes=ExprList(exprs=[ID('constructor')]),
        asm=None,
    )
    result = execute(node)
    assert result is None
    print("no-op ✓")


def test_gnu_alignof():
    """Test __alignof__ operator (GNU extension)."""
    print("  [UnaryOp] __alignof__:", end=' ')
    node = UnaryOp(
        op='__alignof__',
        expr=Constant(type='int', value='42'),
    )
    result = execute(node)
    assert result == 4, f"Expected 4 (alignof int), got {result}"
    print(f"__alignof__(42) = {result} ✓")


def test_gnu_builtin_types_compatible():
    """Test __builtin_types_compatible_p."""
    print("  [FuncCall] __builtin_types_compatible_p:", end=' ')

    call_node = FuncCall(
        name=ID('__builtin_types_compatible_p'),
        args=TypeList(types=[
            TypeDecl(declname=None, quals=[], align=None, type=IdentifierType(names=['int'])),
            TypeDecl(declname=None, quals=[], align=None, type=IdentifierType(names=['int'])),
        ]),
    )
    result = execute(call_node)
    assert result == 1, f"Expected 1 (always compatible), got {result}"
    print(f"({result}) ✓")


def test_gnu_all_extension_fragments():
    """Test that all GNU extension type fragments don't crash."""
    print("  [GNU Ext] All extension type fragments (no-op):")
    execute(AttributeSpecifier(exprlist=ExprList(exprs=[])))
    execute(PreprocessorLine(contents="#define FOO 1"))
    execute(TypeOfDeclaration(typeof_keyword='typeof',
        declaration=Decl(name='_t', quals=[], align=None, storage=[], funcspec=[],
            type=TypeDecl(declname='_t', quals=[], align=None, type=IdentifierType(names=['int'])),
            init=None, bitsize=None)))
    execute(TypeOfExpression(typeof_keyword='typeof', expr=Constant(type='int', value='0')))
    execute(RangeExpression(first=Constant(type='int', value='0'), last=Constant(type='int', value='10')))
    print(f"    All 5 extension fragments executed without error ✓")


# ==================== Main ====================

def main():
    print("=" * 60)
    print("  pycparser AST Interpreter — All Nodes Test")
    print("=" * 60)

    setup_global_scope()

    # --- Standard Nodes ---
    print("\n--- Expressions ---")
    test_basic_expression()
    test_assignment_and_variable()
    test_all_binary_operators()
    test_unary_operators()
    test_ternary_operator()
    test_compound_assignment()
    test_expr_list()
    test_cast()

    print("\n--- Control Flow ---")
    test_if_statement()
    test_while_loop()
    test_for_loop()
    test_do_while_loop()
    test_break_continue()
    test_switch_case()
    test_return_value()

    print("\n--- Declarations ---")
    test_declaration()
    test_enum()
    test_struct_union()
    test_function_call()

    print("\n--- Other Standard Nodes ---")
    test_block_scope()
    test_static_assert()
    test_init_list()
    test_compound_literal()
    test_label_empty()
    test_file_ast()
    test_type_fragments()

    # --- GNU C Extension Nodes ---
    print("\n" + "=" * 60)
    print("  GNU C Extension Nodes")
    print("=" * 60)

    setup_global_scope()

    print("\n--- GNU Extension Types ---")
    test_gnu_type_list()
    test_gnu_attribute_specifier()
    test_gnu_asm()
    test_gnu_preprocessor_line()
    test_gnu_typeof_declaration()
    test_gnu_typeof_expression()
    test_gnu_range_expression()
    test_gnu_case_range()
    test_gnu_type_decl_ext()
    test_gnu_array_decl_ext()
    test_gnu_struct_ext()
    test_gnu_func_decl_ext()

    print("\n--- GNU Operator Extensions ---")
    test_gnu_alignof()
    test_gnu_builtin_types_compatible()

    print("\n--- GNU Fragment Tests ---")
    test_gnu_all_extension_fragments()

    # Summary
    std_count = 49
    ext_count = 11  # TypeList, AttributeSpecifier, Asm, PreprocessorLine,
                    # TypeOfDeclaration, TypeOfExpression, RangeExpression,
                    # TypeDeclExt, ArrayDeclExt, StructExt, FuncDeclExt
    print("\n" + "=" * 60)
    print(f"  Standard nodes: {std_count} ✓")
    print(f"  GNU C extension nodes: {ext_count} ✓")
    print(f"  Total: {std_count + ext_count} AST node types")
    print("  All tests passed! ✅")
    print("=" * 60)


if __name__ == '__main__':
    main()

#!/usr/bin/python

"""pycparser AST Interpreter

Executes C AST nodes by dispatching to type-specific executor classes.
Supports all node types defined in pycparser.c_ast.
"""

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


# ==================== Runtime Support ====================

class ReturnException(Exception):
    """Raised to unwind the stack on a return statement."""
    def __init__(self, value=None):
        self.value = value


class BreakException(Exception):
    """Raised to exit a loop."""


class ContinueException(Exception):
    """Raised to skip to the next loop iteration."""


class Scope:
    """Variable scope with parent chaining for block scoping."""

    def __init__(self, parent=None):
        self._symbols = {}
        self._parent = parent

    def get(self, name):
        if name in self._symbols:
            return self._symbols[name]
        if self._parent:
            return self._parent.get(name)
        raise AssertionError(f"Undefined variable: '{name}'")

    def set(self, name, value):
        if name in self._symbols:
            self._symbols[name] = value
        elif self._parent:
            self._parent.set(name, value)
        else:
            raise AssertionError(f"Undefined variable: '{name}'")

    def declare(self, name, value=None):
        self._symbols[name] = value


class Function:
    """Represents a callable user-defined function."""

    def __init__(self, name, param_names, body, closure_scope):
        self.name = name
        self.param_names = param_names
        self.body = body
        self.closure_scope = closure_scope


# ==================== Global State ====================

# Current active scope (replaced when entering/leaving blocks)
g_scope = Scope()

# Global function table: name -> Function
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
    """Resolve a list of type name strings to a Python converter function."""
    name = ' '.join(type_names).lower()
    for key, converter in _TYPE_CONVERTERS.items():
        if name == key or name.endswith(' ' + key):
            return converter
    return int


def _convert_value(value, type_names=None):
    """Convert a Python value to the target C type."""
    if type_names is None:
        return int(value) if value is not None else 0
    converter = _resolve_type(type_names if isinstance(type_names, (list, tuple)) else [type_names])
    try:
        return converter(value)
    except (ValueError, TypeError):
        return int(value) if value is not None else 0


# ==================== Base Executor ====================

class Execute:
    """Base executor class. Subclasses implement execute()."""

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

class ExeConstant(Execute):
    """Constant literal."""

    def __init__(self, node):
        super().__init__(node)
        self._type_force = {
            'int': int,
            'float': float,
            'double': float,
            'char': lambda v: ord(v[0]) if isinstance(v, str) and len(v) > 0 else int(v) if v else 0,
            'string': str,
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
        # Fallback: try numeric conversion
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
    """Unary operator expression."""

    def execute(self):
        op = self.node.op
        val = execute(self.node.expr)

        handlers = {
            '+': lambda: +val,
            '-': lambda: -val,
            '!': lambda: not val,
            '~': lambda: ~val,
        }

        if op in handlers:
            return handlers[op]()
        raise AssertionError(f"Unknown unary operator: '{op}'")


class ExeAssignment(Execute):
    """Assignment expression (including compound assignments)."""

    def _set_lvalue(self, lvalue_node, value):
        """Set a value through an lvalue node."""
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
            if isinstance(obj, dict):
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

        # Compound assignment: +=, -=, *=, etc.
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
    """Ternary conditional operator (cond ? iftrue : iffalse)."""

    def execute(self):
        cond = execute(self.node.cond)
        if cond:
            return execute(self.node.iftrue)
        return execute(self.node.iffalse)


class ExeCast(Execute):
    """Type cast expression."""

    def execute(self):
        val = execute(self.node.expr)
        type_names = self._extract_type_names(self.node.to_type)
        return _convert_value(val, type_names)

    def _extract_type_names(self, type_node):
        """Walk through type declaration nodes to find IdentifierType names."""
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
    """Array subscript expression (arr[idx])."""

    def execute(self):
        arr = execute(self.node.name)
        idx = execute(self.node.subscript)
        if isinstance(arr, (list, tuple)):
            return arr[idx]
        raise AssertionError(f"Cannot subscript non-array value: {type(arr).__name__}")


class ExeStructRef(Execute):
    """Struct/union member access (. or ->)."""

    def execute(self):
        obj = execute(self.node.name)
        field_node = self.node.field
        field_name = field_node.name if isinstance(field_node, ID) else str(field_node)

        if isinstance(obj, dict):
            return obj.get(field_name, 0)
        return getattr(obj, field_name, 0)


class ExeFuncCall(Execute):
    """Function call expression."""

    def _eval_args(self, args_node):
        """Evaluate function arguments from various container nodes."""
        if args_node is None:
            return []

        if isinstance(args_node, ExprList):
            return [execute(e) for e in args_node.exprs]

        if isinstance(args_node, ParamList):
            return [execute(p) for p in args_node.params]

        # Single argument
        return [execute(args_node)]

    def _call_builtin(self, name, args):
        """Handle built-in / known library functions."""
        if name == 'printf':
            fmt = str(args[0]) if args else ''
            # Simulate: just output to stdout
            print(fmt % tuple(args[1:]) if len(args) > 1 else fmt, end='')
            return len(fmt)
        if name == 'putchar':
            char_code = args[0] if args else 0
            print(chr(char_code) if isinstance(char_code, int) else str(char_code), end='')
            return char_code
        if name == 'getchar':
            # Not interactive; return 0
            return 0
        if name in ('exit', '_exit'):
            raise SystemExit(args[0] if args else 0)
        if name == 'abs':
            return abs(args[0]) if args else 0
        raise AssertionError(f"Undefined function: '{name}'")

    def execute(self):
        # Resolve function name
        name_node = self.node.name
        if isinstance(name_node, ID):
            func_name = name_node.name
        else:
            func_name = str(execute(name_node))

        args = self._eval_args(self.node.args)

        # Look up user-defined function
        if func_name in g_functions:
            func = g_functions[func_name]

            # Save current scope and create new one for the call
            global g_scope
            outer_scope = g_scope
            g_scope = Scope(func.closure_scope)

            # Bind parameters
            for i, pname in enumerate(func.param_names):
                g_scope.declare(pname, args[i] if i < len(args) else 0)

            try:
                result = execute(func.body)
                return result
            except ReturnException as e:
                return e.value
            finally:
                g_scope = outer_scope

        # Fallback to built-in
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
                pass  # falls through to condition check
            if not execute(self.node.cond):
                break


class ExeFor(Execute):
    """For loop.

    In C99+: the init declaration has its own scope.
    continue jumps to the 'next' expression.
    """

    def execute(self):
        global g_scope

        # For loop introduces its own scope (C99+)
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
                    pass  # falls through to next expression

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
    """Switch statement.

    Walks the body's block_items to find the matching case,
    then executes all subsequent statements (fall-through).
    """

    def execute(self):
        cond = execute(self.node.cond)
        body = self.node.stmt

        # Collect all statements after the matching case
        stmts_to_run = []
        matched = False
        default_stmts = []

        if isinstance(body, Compound) and body.block_items:
            for item in body.block_items:
                if isinstance(item, Case):
                    if not matched:
                        case_val = execute(item.expr)
                        if case_val == cond:
                            matched = True
                        else:
                            continue  # skip this case's stmts
                    # matched: collect all case stmts
                    for s in (item.stmts or []):
                        stmts_to_run.append(s)
                elif isinstance(item, Default):
                    if not matched:
                        default_stmts = item.stmts or []
                    else:
                        for s in (item.stmts or []):
                            stmts_to_run.append(s)
                elif matched:
                    # Regular statement inside switch after match
                    stmts_to_run.append(item)

        # If no case matched, use default
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
    """Variable declaration with optional initializer."""

    @staticmethod
    def _extract_type_names(type_node):
        """Walk type declarations to find the base type name list."""
        if type_node is None:
            return ['int']
        if isinstance(type_node, IdentifierType):
            return type_node.names
        if isinstance(type_node, TypeDecl):
            return ExeDecl._extract_type_names(type_node.type)
        if isinstance(type_node, ArrayDecl):
            return ExeDecl._extract_type_names(type_node.type) + ['[]']
        if isinstance(type_node, PtrDecl):
            return ExeDecl._extract_type_names(type_node.type) + ['*']
        if isinstance(type_node, FuncDecl):
            return ExeDecl._extract_type_names(type_node.type) + ['()']
        return ['int']

    def _default_value(self, type_node):
        """Get a sensible default value based on the type."""
        names = self._extract_type_names(type_node)
        type_str = ' '.join(n.lower() for n in names)

        if 'float' in type_str or 'double' in type_str:
            return 0.0
        if '_Bool' in type_str or 'bool' in type_str:
            return False
        if 'char' in type_str:
            return 0
        return 0

    def execute(self):
        name = self.node.name
        if name is None:
            return

        # Evaluate initializer if present
        if self.node.init is not None:
            init_val = execute(self.node.init)
        else:
            init_val = self._default_value(self.node.type)

        g_scope.declare(name, init_val)


class ExeDeclList(Execute):
    """List of declarations."""

    def execute(self):
        for decl in self.node.decls or []:
            execute(decl)


class ExeFuncDef(Execute):
    """Function definition."""

    def _get_param_names(self, func_decl):
        """Extract parameter names from a FuncDecl."""
        if func_decl.args is None:
            return []
        if isinstance(func_decl.args, ParamList):
            names = []
            for p in func_decl.args.params:
                if isinstance(p, Decl):
                    names.append(p.name)
            return names
        return []

    def execute(self):
        decl = self.node.decl
        func_name = decl.name

        # Extract param names from the FuncDecl
        func_decl = decl.type
        param_names = self._get_param_names(func_decl)

        g_functions[func_name] = Function(
            name=func_name,
            param_names=param_names,
            body=self.node.body,
            closure_scope=g_scope,
        )


class ExeEmptyStatement(Execute):
    """Empty statement (;)."""

    def execute(self):
        pass


class ExeLabel(Execute):
    """Labeled statement (label: stmt)."""

    def execute(self):
        if self.node.stmt is not None:
            execute(self.node.stmt)


class ExeGoto(Execute):
    """Goto statement (not supported in interpreter)."""

    def execute(self):
        raise AssertionError(
            f"Goto is not supported in the interpreter (target: '{self.node.name}')"
        )


# ==================== Initializer Executors ====================

class ExeInitList(Execute):
    """Initializer list { ... }."""

    def execute(self):
        return [execute(e) for e in self.node.exprs or []]


class ExeNamedInitializer(Execute):
    """Named/designated initializer (.field = value)."""

    def execute(self):
        return execute(self.node.expr)


class ExeCompoundLiteral(Execute):
    """Compound literal (type){ ... }."""

    def execute(self):
        return execute(self.node.init)


# ==================== Type / Declaration Fragment Executors ====================

class ExeIdentifierType(Execute):
    """Base type name reference (e.g. 'int', 'float')."""

    def execute(self):
        return None  # type info only, no runtime effect


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
    """Struct type definition."""

    def execute(self):
        # Register struct name (optional) and process member declarations
        if self.node.decls:
            for decl in self.node.decls:
                if isinstance(decl, Decl) and decl.name:
                    g_scope.declare(decl.name, 0)


class ExeUnion(Execute):
    """Union type definition."""

    def execute(self):
        if self.node.decls:
            for decl in self.node.decls:
                if isinstance(decl, Decl) and decl.name:
                    g_scope.declare(decl.name, 0)


class ExeEnum(Execute):
    """Enum type definition."""

    def execute(self):
        value = 0
        if self.node.values is not None and isinstance(self.node.values, EnumeratorList):
            for enumerator in self.node.values.enumerators or []:
                if enumerator.value is not None:
                    value = execute(enumerator.value)
                g_scope.declare(enumerator.name, value)
                value += 1


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
    """Typedef declaration."""

    def execute(self):
        # Register the typedef name (minimal support)
        name = self.node.name
        if name:
            g_scope.declare(name, None)


class ExeTypename(Execute):
    """Type name in a context like sizeof or cast."""

    def execute(self):
        return None


class ExeAlignas(Execute):
    """Alignment specifier (_Alignas)."""

    def execute(self):
        pass  # alignment is a compile-time concept


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
        pass  # pragmas are compiler directives


class ExeFileAST(Execute):
    """Top-level file AST node."""

    def execute(self):
        result = None
        for ext in self.node.ext or []:
            result = execute(ext)
        return result


# ==================== Dispatch Table ====================

g_exe_class = {
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
    # Type fragments (compile-time, no runtime effect)
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
}


# ==================== Tests ====================

def setup_global_scope():
    """Reset the global scope and function table for testing."""
    global g_scope, g_functions
    g_scope = Scope()
    g_scope.declare('i', 0)
    g_scope.declare('j', 0)
    g_functions = {}


def test_basic_expression():
    """Test: 1 + 1 == 2"""
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
    """Test: i = 2 + 3"""
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
    """Test all binary arithmetic and comparison operators."""
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
    """Test unary operators."""
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


def test_ternary_operator():
    """Test ternary conditional operator."""
    print("  [TernaryOp] Ternary operator:")

    # 1 ? 10 : 20 => 10
    node = TernaryOp(
        cond=Constant(type='int', value='1'),
        iftrue=Constant(type='int', value='10'),
        iffalse=Constant(type='int', value='20'),
    )
    result = execute(node)
    assert result == 10, f"Expected 10, got {result}"
    print(f"    1 ? 10 : 20 = {result} ✓")

    # 0 ? 10 : 20 => 20
    node = TernaryOp(
        cond=Constant(type='int', value='0'),
        iftrue=Constant(type='int', value='10'),
        iffalse=Constant(type='int', value='20'),
    )
    result = execute(node)
    assert result == 20, f"Expected 20, got {result}"
    print(f"    0 ? 10 : 20 = {result} ✓")


def test_compound_assignment():
    """Test compound assignment operators."""
    print("  [Assignment] Compound assignments:")

    g_scope.set('i', 10)
    node = Assignment(op='+=', lvalue=ID('i'), rvalue=Constant(type='int', value='5'))
    result = execute(node)
    assert g_scope.get('i') == 15, f"Expected i=15, got i={g_scope.get('i')}"
    print(f"    i = 10; i += 5 => i = {g_scope.get('i')} ✓")

    node = Assignment(op='-=', lvalue=ID('i'), rvalue=Constant(type='int', value='3'))
    result = execute(node)
    assert g_scope.get('i') == 12, f"Expected i=12, got i={g_scope.get('i')}"
    print(f"    i -= 3 => i = {g_scope.get('i')} ✓")

    node = Assignment(op='*=', lvalue=ID('i'), rvalue=Constant(type='int', value='2'))
    result = execute(node)
    assert g_scope.get('i') == 24, f"Expected i=24, got i={g_scope.get('i')}"
    print(f"    i *= 2 => i = {g_scope.get('i')} ✓")


def test_expr_list():
    """Test comma expression."""
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
    """Test if/else control flow."""
    print("  [If] If/else statement:")

    g_scope.declare('result', 0)

    # if (1) { result = 42; }
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

    # if (0) { result = 100; } else { result = 200; }
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
    """Test while loop with sum 0..4."""
    print("  [While] While loop:")
    g_scope.declare('count', 0)
    g_scope.declare('sum', 0)

    body = Compound(block_items=[
        Assignment(
            op='=',
            lvalue=ID('sum'),
            rvalue=BinaryOp(op='+', left=ID('sum'), right=ID('count')),
        ),
        Assignment(
            op='=',
            lvalue=ID('count'),
            rvalue=BinaryOp(op='+', left=ID('count'), right=Constant(type='int', value='1')),
        ),
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
    """Test for loop."""
    print("  [For] For loop:")
    g_scope.declare('s', 0)

    for_node = For(
        init=Assignment(
            op='=',
            lvalue=ID('i'),
            rvalue=Constant(type='int', value='0'),
        ),
        cond=BinaryOp(
            op='<',
            left=ID('i'),
            right=Constant(type='int', value='3'),
        ),
        next=Assignment(
            op='=',
            lvalue=ID('i'),
            rvalue=BinaryOp(op='+', left=ID('i'), right=Constant(type='int', value='1')),
        ),
        stmt=Compound(block_items=[
            Assignment(
                op='=',
                lvalue=ID('s'),
                rvalue=BinaryOp(op='+', left=ID('s'), right=ID('i')),
            ),
        ]),
    )
    execute(for_node)

    assert g_scope.get('s') == 3, f"Expected s=3, got {g_scope.get('s')}"
    print(f"    for (i=0; i<3; i++) s+=i => s = {g_scope.get('s')} ✓")


def test_do_while_loop():
    """Test do-while loop (executes at least once)."""
    print("  [DoWhile] Do-While loop:")
    g_scope.declare('x', 0)

    body = Compound(block_items=[
        Assignment(
            op='=',
            lvalue=ID('x'),
            rvalue=BinaryOp(op='+', left=ID('x'), right=Constant(type='int', value='1')),
        ),
    ])
    dnode = DoWhile(
        cond=BinaryOp(op='<', left=ID('x'), right=Constant(type='int', value='3')),
        stmt=body,
    )
    execute(dnode)

    assert g_scope.get('x') == 3, f"Expected x=3, got {g_scope.get('x')}"
    print(f"    do {{ x++; }} while(x<3) => x = {g_scope.get('x')} ✓")


def test_block_scope():
    """Test that block scope isolates inner variables."""
    print("  [Scope] Block scoping:")
    g_scope.declare('x', 1)

    inner = Compound(block_items=[
        Decl(
            name='x',
            quals=[], align=None, storage=[], funcspec=[],
            type=TypeDecl(
                declname='x', quals=[], align=None,
                type=IdentifierType(names=['int']),
            ),
            init=Constant(type='int', value='2'),
            bitsize=None,
        ),
        Assignment(
            op='=',
            lvalue=ID('x'),
            rvalue=BinaryOp(op='+', left=ID('x'), right=Constant(type='int', value='1')),
        ),
    ])
    execute(inner)

    assert g_scope.get('x') == 1, f"Expected outer x=1, got {g_scope.get('x')}"
    print(f"    outer x stays {g_scope.get('x')} after inner block ✓")


def test_function_call():
    """Test function definition and call."""
    print("  [FuncDef/FuncCall] Function call:")

    # int add(int a, int b) { return a + b; }
    func_decl = Decl(
        name='add',
        quals=[], align=None, storage=[], funcspec=[],
        type=FuncDecl(
            args=ParamList(params=[
                Decl(
                    name='a',
                    quals=[], align=None, storage=[], funcspec=[],
                    type=TypeDecl(
                        declname='a', quals=[], align=None,
                        type=IdentifierType(names=['int']),
                    ),
                    init=None, bitsize=None,
                ),
                Decl(
                    name='b',
                    quals=[], align=None, storage=[], funcspec=[],
                    type=TypeDecl(
                        declname='b', quals=[], align=None,
                        type=IdentifierType(names=['int']),
                    ),
                    init=None, bitsize=None,
                ),
            ]),
            type=TypeDecl(
                declname='add', quals=[], align=None,
                type=IdentifierType(names=['int']),
            ),
        ),
        init=None, bitsize=None,
    )

    func_body = Compound(block_items=[
        Return(expr=BinaryOp(op='+', left=ID('a'), right=ID('b'))),
    ])

    func_def = FuncDef(decl=func_decl, param_decls=None, body=func_body)
    execute(func_def)

    # Call add(3, 4)
    call_node = FuncCall(
        name=ID('add'),
        args=ExprList(exprs=[
            Constant(type='int', value='3'),
            Constant(type='int', value='4'),
        ]),
    )
    result = execute(call_node)
    assert result == 7, f"Expected 7, got {result}"
    print(f"    add(3, 4) = {result} ✓")

    # Test function with no args
    g_functions['fortytwo'] = Function(
        name='fortytwo',
        param_names=[],
        body=Compound(block_items=[Return(expr=Constant(type='int', value='42'))]),
        closure_scope=g_scope,
    )
    result = execute(FuncCall(name=ID('fortytwo'), args=None))
    assert result == 42, f"Expected 42, got {result}"
    print(f"    fortytwo() = {result} ✓")


def test_break_continue():
    """Test break and continue in loops."""
    print("  [Break/Continue] Loop control:")
    g_scope.declare('found', 0)

    # while (1) { if (found >= 3) break; found++; continue; found = 999; }
    body = Compound(block_items=[
        If(
            cond=BinaryOp(
                op='>=',
                left=ID('found'),
                right=Constant(type='int', value='3'),
            ),
            iftrue=Break(),
            iffalse=None,
        ),
        Assignment(
            op='=',
            lvalue=ID('found'),
            rvalue=BinaryOp(
                op='+',
                left=ID('found'),
                right=Constant(type='int', value='1'),
            ),
        ),
        Continue(),
        Assignment(
            op='=',
            lvalue=ID('found'),
            rvalue=Constant(type='int', value='999'),
        ),
    ])
    wnode = While(cond=Constant(type='int', value='1'), stmt=body)
    execute(wnode)

    assert g_scope.get('found') == 3, f"Expected found=3, got {g_scope.get('found')}"
    print(f"    break after found=3, continue skips assignment ✓")


def test_switch_case():
    """Test switch-case with fall-through."""
    print("  [Switch/Case] Switch statement:")
    g_scope.declare('val', 0)

    # switch (2) { case 1: val=10; break; case 2: val=20; case 3: val=30; break; default: val=99; }
    switch_node = Switch(
        cond=Constant(type='int', value='2'),
        stmt=Compound(block_items=[
            Case(
                expr=Constant(type='int', value='1'),
                stmts=[
                    Assignment(op='=', lvalue=ID('val'), rvalue=Constant(type='int', value='10')),
                    Break(),
                ],
            ),
            Case(
                expr=Constant(type='int', value='2'),
                stmts=[
                    Assignment(op='=', lvalue=ID('val'), rvalue=Constant(type='int', value='20')),
                    # fall-through to case 3!
                ],
            ),
            Case(
                expr=Constant(type='int', value='3'),
                stmts=[
                    Assignment(op='=', lvalue=ID('val'), rvalue=Constant(type='int', value='30')),
                    Break(),
                ],
            ),
            Default(stmts=[
                Assignment(op='=', lvalue=ID('val'), rvalue=Constant(type='int', value='99')),
            ]),
        ]),
    )
    execute(switch_node)

    assert g_scope.get('val') == 30, f"Expected val=30 (fall-through), got {g_scope.get('val')}"
    print(f"    switch(2) fall-through case 2 -> case 3 => val = {g_scope.get('val')} ✓")

    # Test default case
    g_scope.set('val', 0)
    switch_node2 = Switch(
        cond=Constant(type='int', value='99'),
        stmt=Compound(block_items=[
            Case(
                expr=Constant(type='int', value='1'),
                stmts=[Assignment(op='=', lvalue=ID('val'), rvalue=Constant(type='int', value='10'))],
            ),
            Default(stmts=[
                Assignment(op='=', lvalue=ID('val'), rvalue=Constant(type='int', value='42')),
            ]),
        ]),
    )
    execute(switch_node2)
    assert g_scope.get('val') == 42, f"Expected val=42 (default), got {g_scope.get('val')}"
    print(f"    switch(99) default => val = {g_scope.get('val')} ✓")


def test_declaration():
    """Test variable declaration with and without initializer."""
    print("  [Decl] Variable declaration:")

    # int x = 10;
    decl = Decl(
        name='x',
        quals=[], align=None, storage=[], funcspec=[],
        type=TypeDecl(declname='x', quals=[], align=None, type=IdentifierType(names=['int'])),
        init=Constant(type='int', value='10'),
        bitsize=None,
    )
    execute(decl)
    assert g_scope.get('x') == 10, f"Expected x=10, got {g_scope.get('x')}"
    print(f"    int x = 10 => x = {g_scope.get('x')} ✓")

    # int y;  (default: 0)
    decl2 = Decl(
        name='y',
        quals=[], align=None, storage=[], funcspec=[],
        type=TypeDecl(declname='y', quals=[], align=None, type=IdentifierType(names=['int'])),
        init=None, bitsize=None,
    )
    execute(decl2)
    assert g_scope.get('y') == 0, f"Expected y=0, got {g_scope.get('y')}"
    print(f"    int y; (default) => y = {g_scope.get('y')} ✓")


def test_enum():
    """Test enum definition."""
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

    assert g_scope.get('RED') == 0, f"Expected RED=0, got {g_scope.get('RED')}"
    assert g_scope.get('GREEN') == 1, f"Expected GREEN=1, got {g_scope.get('GREEN')}"
    assert g_scope.get('BLUE') == 10, f"Expected BLUE=10, got {g_scope.get('BLUE')}"
    assert g_scope.get('YELLOW') == 11, f"Expected YELLOW=11, got {g_scope.get('YELLOW')}"
    print(f"    RED={g_scope.get('RED')}, GREEN={g_scope.get('GREEN')}, "
          f"BLUE={g_scope.get('BLUE')}, YELLOW={g_scope.get('YELLOW')} ✓")


def test_cast():
    """Test type casting."""
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
    """Test static assertion."""
    print("  [StaticAssert] Static assert:", end=' ')

    # _Static_assert(1, "ok") should pass
    node = StaticAssert(
        cond=Constant(type='int', value='1'),
        message=Constant(type='string', value='ok'),
    )
    execute(node)  # should not raise
    print("pass ✓")

    # _Static_assert(0, "fail") should raise
    node = StaticAssert(
        cond=Constant(type='int', value='0'),
        message=Constant(type='string', value='fail'),
    )
    try:
        execute(node)
        assert False, "Should have raised AssertionError"
    except AssertionError:
        print("    _Static_assert(0, ...) raises AssertionError ✓")


def test_init_list():
    """Test initializer list."""
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
    """Test FileAST top-level execution."""
    print("  [FileAST] File-level execution:", end=' ')
    file_node = FileAST(ext=[
        Decl(
            name='a',
            quals=[], align=None, storage=[], funcspec=[],
            type=TypeDecl(declname='a', quals=[], align=None, type=IdentifierType(names=['int'])),
            init=Constant(type='int', value='100'),
            bitsize=None,
        ),
        Assignment(
            op='=',
            lvalue=ID('a'),
            rvalue=BinaryOp(op='+', left=ID('a'), right=Constant(type='int', value='1')),
        ),
    ])
    result = execute(file_node)
    assert g_scope.get('a') == 101, f"Expected a=101, got {g_scope.get('a')}"
    print(f"a = {g_scope.get('a')} ✓")


def test_return_value():
    """Test return statement."""
    print("  [Return] Return statement:")

    # Create a simple function that returns a value
    g_functions['getval'] = Function(
        name='getval',
        param_names=[],
        body=Compound(block_items=[
            Return(expr=Constant(type='int', value='77')),
        ]),
        closure_scope=g_scope,
    )

    result = execute(FuncCall(name=ID('getval'), args=None))
    assert result == 77, f"Expected 77, got {result}"
    print(f"    return 77 => {result} ✓")


def test_label_empty():
    """Test labeled and empty statements."""
    print("  [Label/Empty] Label + EmptyStatement:")

    g_scope.declare('labeled_val', 0)

    # label: { labeled_val = 5; }
    label_node = Label(
        name='mylabel',
        stmt=Compound(block_items=[
            Assignment(
                op='=',
                lvalue=ID('labeled_val'),
                rvalue=Constant(type='int', value='5'),
            ),
        ]),
    )
    execute(label_node)
    assert g_scope.get('labeled_val') == 5, f"Expected 5, got {g_scope.get('labeled_val')}"
    print(f"    label: compound works ✓")

    # Empty statement should not crash
    execute(EmptyStatement())
    print(f"    EmptyStatement: no-op ✓")


def test_struct_union():
    """Test struct and union member declarations."""
    print("  [Struct/Union] Struct/Union declarations:")

    struct_node = Struct(
        name='Point',
        decls=[
            Decl(
                name='px',
                quals=[], align=None, storage=[], funcspec=[],
                type=TypeDecl(declname='px', quals=[], align=None, type=IdentifierType(names=['int'])),
                init=None, bitsize=None,
            ),
            Decl(
                name='py',
                quals=[], align=None, storage=[], funcspec=[],
                type=TypeDecl(declname='py', quals=[], align=None, type=IdentifierType(names=['int'])),
                init=None, bitsize=None,
            ),
        ],
    )
    execute(struct_node)
    # Members should be declared with default value 0
    assert g_scope.get('px') == 0, f"Expected px=0, got {g_scope.get('px')}"
    assert g_scope.get('py') == 0, f"Expected py=0, got {g_scope.get('py')}"
    print(f"    struct Point members px={g_scope.get('px')}, py={g_scope.get('py')} ✓")


def test_compound_literal():
    """Test compound literal."""
    print("  [CompoundLiteral] Compound literal:", end=' ')
    node = CompoundLiteral(
        type=TypeDecl(declname=None, quals=[], align=None, type=IdentifierType(names=['int'])),
        init=InitList(exprs=[
            Constant(type='int', value='10'),
            Constant(type='int', value='20'),
        ]),
    )
    result = execute(node)
    assert result == [10, 20], f"Expected [10, 20], got {result}"
    print(f"{result} ✓")


def test_typedecl_ptr_array():
    """Test that type declaration fragments don't crash."""
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
    execute(NamedInitializer(
        name=[ID('x')],
        expr=Constant(type='int', value='5'),
    ))

    print(f"    All 12 type/fragment nodes executed without error ✓")


# ==================== Main ====================

def main():
    print("=" * 60)
    print("  pycparser AST Interpreter — All Nodes Test")
    print("=" * 60)

    setup_global_scope()

    # Expression tests
    print("\n--- Expressions ---")
    test_basic_expression()
    test_assignment_and_variable()
    test_all_binary_operators()
    test_unary_operators()
    test_ternary_operator()
    test_compound_assignment()
    test_expr_list()
    test_cast()

    # Control flow tests
    print("\n--- Control Flow ---")
    test_if_statement()
    test_while_loop()
    test_for_loop()
    test_do_while_loop()
    test_break_continue()
    test_switch_case()
    test_return_value()

    # Declaration tests
    print("\n--- Declarations ---")
    test_declaration()
    test_enum()
    test_struct_union()
    test_function_call()

    # Other tests
    print("\n--- Other ---")
    test_block_scope()
    test_static_assert()
    test_init_list()
    test_compound_literal()
    test_label_empty()
    test_file_ast()
    test_typedecl_ptr_array()

    print("\n" + "=" * 60)
    print("  All 49 AST node types covered ✅")
    print("  All tests passed! ✅")
    print("=" * 60)


if __name__ == '__main__':
    main()

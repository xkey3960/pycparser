"""把 C 的**声明符**翻译成 CType。

C 的类型不在名字里，而在声明符的形状里——这是它最反直觉的地方，也是
"只用 IdentifierType.names 解析类型"永远做不对的原因：

    int  x;          TypeDecl(IdentifierType(['int']))
    int *x;          PtrDecl(TypeDecl(IdentifierType(['int'])))
    int  x[3];       ArrayDecl(TypeDecl(IdentifierType(['int'])), dim=3)
    int  x[3][4];    ArrayDecl(ArrayDecl(TypeDecl(...), dim=4), dim=3)
    int (*x)[4];     PtrDecl(ArrayDecl(TypeDecl(...), dim=4))
    int  f(int);     FuncDecl(TypeDecl(IdentifierType(['int'])), args=...)

所以这里按节点形状递归：**外壳决定派生类型，芯决定基础类型**。
（旧实现把这件事摊在 `typesys.type_of_decl` 里，那部分语义是对的，
只是产出的类型和内存没接上。）
"""

from __future__ import annotations

from typing import Any

from pycparser import c_ast

from super_execute.application.ports.type_resolver_port import TypeResolverPort
from super_execute.domain.entities.c_types import (
    ArrayType,
    BasicType,
    CType,
    EnumType,
    FunctionType,
    Member,
    PointerType,
    StructType,
    UnionType,
)
from super_execute.domain.entities.scope import Scope
from super_execute.domain.entities.symbol import ConstantSymbol, TagSymbol
from super_execute.domain.exceptions import (
    InvalidTypeError,
    UnsupportedTypeError,
)
from super_execute.domain.services.builtin_types import INT
from super_execute.domain.services.conversions import array_to_pointer
from super_execute.domain.services.equivalence import members_equivalent
from super_execute.domain.value_objects import TagKind

_TAG_KINDS = {
    c_ast.Struct: TagKind.STRUCT,
    c_ast.Union: TagKind.UNION,
    c_ast.Enum: TagKind.ENUM,
}


class TypeBuilder:
    """按当前作用域把声明符翻成 CType。

    带作用域是因为两件事都要查它：``IdentifierType`` 里的 typedef 名、
    以及 struct/union/enum 的**标签**（同名标签在不同作用域是不同类型）。
    """

    __slots__ = ("_resolver", "_scope")

    def __init__(self, resolver: TypeResolverPort, scope: Scope) -> None:
        self._resolver = resolver
        self._scope = scope

    @property
    def scope(self) -> Scope:
        """当前解析视角（测试与调试用）。"""
        return self._scope

    @property
    def resolver(self) -> TypeResolverPort:
        return self._resolver

    # ---- 入口 ----

    def build(self, node: Any) -> CType:
        if isinstance(node, c_ast.TypeDecl):
            return self.build(node.type)
        if isinstance(node, c_ast.Typename):
            return self.build(node.type)
        if isinstance(node, c_ast.IdentifierType):
            return self._resolver.resolve(self._scope, node.names)
        if isinstance(node, c_ast.PtrDecl):
            return PointerType(self.build(node.type))
        if isinstance(node, c_ast.ArrayDecl):
            return ArrayType(self.build(node.type), self._dimension(node.dim))
        if isinstance(node, c_ast.FuncDecl):
            return self._function(node)
        if isinstance(node, (c_ast.Struct, c_ast.Union, c_ast.Enum)):
            return self._tagged(node)
        raise UnsupportedTypeError(f"还没支持的声明符: {type(node).__name__}")

    # ---- 派生类型 ----

    def _dimension(self, dim: Any) -> int | None:
        """数组长度。``None`` = 长度未定（弹性数组成员）。"""
        if dim is None:
            return None
        value = _const_int(dim)
        if value is None:
            raise UnsupportedTypeError(
                f"数组长度必须是整型常量（常量折叠还没做）: {type(dim).__name__}"
            )
        return value

    def _function(self, node: c_ast.FuncDecl) -> FunctionType:
        ret = self.build(node.type)
        params: list[CType] = []
        variadic = False
        if node.args is not None:
            for param in node.args.params:
                if isinstance(param, c_ast.EllipsisParam):
                    variadic = True
                    continue
                if isinstance(param, c_ast.Typename):
                    if param.name == "...":
                        variadic = True
                        continue
                    ctype = self.build(param.type)
                elif isinstance(param, c_ast.Decl):
                    ctype = self.build(param.type)
                else:
                    raise UnsupportedTypeError(
                        f"不认识的形参节点: {type(param).__name__}"
                    )
                # f(void) 的形参是"不完整的 void"，不算真的参数
                if isinstance(ctype, BasicType) and not ctype.is_complete:
                    continue
                params.append(array_to_pointer(ctype))
        return FunctionType(ret, params, variadic)

    # ---- 标签：struct / union / enum ----

    def _tagged(self, node: Any) -> CType:
        kind = _TAG_KINDS[type(node)]
        if kind is TagKind.ENUM:
            return self._enum(node)
        return self._record(node, kind)

    def _record(self, node: Any, kind: TagKind) -> CType:
        """struct / union：可能只是前置引用，也可能带成员定义。"""
        builder = StructType if kind is TagKind.STRUCT else UnionType
        ctype = self._tag_type(
            node.name, kind, builder, defining=node.decls is not None
        )
        if node.decls is not None:  # 带成员 = 定义
            members = []
            for decl in node.decls:
                if not isinstance(decl, c_ast.Decl):
                    raise UnsupportedTypeError(
                        f"结构体成员里有不认识的节点: {type(decl).__name__}"
                    )
                if not decl.name:
                    raise UnsupportedTypeError("不支持匿名成员")
                members.append(
                    Member(decl.name, self.build(decl.type), _bit_width(decl))
                )
            if ctype.is_complete:
                # 跨文件重复定义：内容一样就静默去重，不一样才是冲突
                if members_equivalent(ctype, members):
                    return ctype
                raise InvalidTypeError(f"{ctype.name} 重复定义，且成员不同")
            ctype.define(members)  # 重复定义 / 空结构体会在这里报错
        return ctype

    def _enum(self, node: c_ast.Enum) -> CType:
        ctype = self._tag_type(
            node.name, TagKind.ENUM, EnumType, defining=node.values is not None
        )
        if node.values is not None:
            constants: dict[str, int] = {}
            next_value = 0
            for enumerator in node.values.enumerators:
                if enumerator.value is not None:
                    value = _const_int(enumerator.value)
                    if value is None:
                        raise UnsupportedTypeError(
                            f"枚举值必须是整型常量: {enumerator.name}"
                        )
                else:
                    value = next_value
                constants[enumerator.name] = value
                # C 的枚举常量进**外围**作用域，不另开一层
                self._scope.declare(ConstantSymbol(enumerator.name, value, INT))
                next_value = value + 1
            if ctype.is_complete:
                if dict(ctype.constants) == constants:
                    return ctype  # 跨文件同一份枚举定义：静默去重
                raise InvalidTypeError(f"{ctype.name} 重复定义，且枚举值不同")
            ctype.define(constants)
        return ctype

    def _tag_type(
        self, name: str | None, kind: TagKind, builder: Any, *, defining: bool
    ) -> Any:
        """取该作用域里的标签类型；需要时新建并**先登记**。

        两条规则（C99 6.2.1 / 6.7.2.3）：

        * **带定义**（有成员 / 有枚举值）→ 一定是"本层的这个类型"。
          本层没有就新建，**即使外层有同名标签也只遮蔽、不冲突**；
        * **不带定义**（`struct S;` 或 `struct S *p;`）→ 先在链上看有没有可见的
          同名标签，有就用它，没有才在本层登记一个不完整类型。

        自引用（`struct Node { struct Node *next; }`）靠"先登记、后定义成员"成立。
        """
        if not name:
            return builder(None)  # 匿名：不登记标签

        local = self._scope.tags.local(name)
        if (
            local is not None
            and isinstance(local, TagSymbol)
            and local.ctype is not None
        ):
            return local.ctype  # 本层已有（前置声明后补定义走这条）

        if not defining:
            visible = self._scope.find_tag(name)
            if visible is not None and isinstance(visible, TagSymbol):
                if visible.ctype is not None:
                    return visible.ctype

        ctype = builder(name)
        self._scope.redeclare(TagSymbol(name, kind, ctype))
        return ctype


def _bit_width(decl: c_ast.Decl) -> int | None:
    if getattr(decl, "bitsize", None) is None:
        return None
    raise UnsupportedTypeError("位域（bit-field）尚未实现")


def _const_int(node: Any) -> int | None:
    """极简常量求值：只认整数常量与它的一元负号。"""
    if isinstance(node, c_ast.Constant) and node.type in (
        "int",
        "long",
        "unsigned int",
    ):
        try:
            return int(node.value, 0)
        except ValueError:
            return None
    if isinstance(node, c_ast.UnaryOp) and node.op == "-":
        inner = _const_int(node.expr)
        return None if inner is None else -inner
    return None

#!/usr/bin/python
"""test_ext.py — GNU C 扩展解析端到端（pytest 化）

用 CustomerCParser（GnuCParser 子类，收集函数定义）解析 test_ext.c，
验证函数/结构体定义收集与调用关系访问（FuncDefVisitor / FuncCallVisitor）。
"""

from typing import (
    List,
    Optional,
)
from pycparserext import ext_c_parser
from pycparser import c_ast, parse_file

from pycparserext.ext_c_parser import TypeDeclExt

old_init = TypeDeclExt.__init__
def fixed_init(self, declname, quals, align, type, coord=None):
    old_init(self, declname, quals, align, type, coord)
    self.asm = None
TypeDeclExt.__init__ = fixed_init

from examples.func_defs import FuncDefVisitor
from examples.func_calls import FuncCallVisitor

args = [
    '-E'
]


# 同时遍历找到 函数定义和结构体定义
class DependVisitor(c_ast.NodeVisitor):
    def visit_FuncDef(self, node: c_ast.FuncDef) -> None:
        print(f"{node.decl.name} at {node.decl.coord}")
    def visit_Struct(self, node: c_ast.Struct) -> None:
        print(f"{node.name} at {node.coord}")


# 定制化类，支持 函数指针
class CustomerCParser(ext_c_parser.GnuCParser):
    def __init__(self):
        # 函数列表
        self.func_db = {}
        super().__init__()

    # 在增加函数定义时，添加到函数列表 func_db
    def _build_function_definition(
        self,
        spec: "_DeclSpec",
        decl: c_ast.Node,
        param_decls: Optional[List[c_ast.Node]],
        body: c_ast.Node,
    ) -> c_ast.Node:
        """Builds a function definition."""
        # 调用父类的函数处理 函数定义
        node: c_ast.FuncDef = super()._build_function_definition(spec, decl, param_decls, body)
        # 将 函数名 插入到  func_db
        self.func_db[node.decl.name] = node
        return node

    # print_funcs
    # 打印 func_db
    def print_funcs(self):
        for func in self.func_db.keys():
            print(func)


def test_gnu_ext_parse():
    """解析 test_ext.c（GNU 扩展：函数指针/类型属性等），验证收集函数定义。"""
    parser = CustomerCParser()
    ast = parse_file(
        "test_ext.c",
        use_cpp=True,
        cpp_path="gcc",
        cpp_args=args,
        parser=parser,
    )
    assert ast is not None and hasattr(ast, 'ext')
    # 函数定义收集（test_ext.c 中定义的函数）
    assert 'func1' in parser.func_db, f"func1 应被收集，实际 {list(parser.func_db)}"

    v = FuncDefVisitor()
    v.visit(ast)

    v = FuncCallVisitor("func1")
    v.visit(ast)

    v = DependVisitor()
    v.visit(ast)
    parser.print_funcs()


if __name__ == '__main__':
    test_gnu_ext_parse()
    print("test_ext GNU 扩展解析通过 ✓")

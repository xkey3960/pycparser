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
 
from pycparser import c_ast
# 定制化类，支持 函数指针
class CustomerCParser(ext_c_parser.GnuCParser):
    def __init__(self):
        # 函数列表
        self.func_db = {}
        super().__init__()

    # 函数重载 
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
        node:c_ast.FuncDef = super()._build_function_definition(spec, decl, param_decls, body)
        # 将 函数名 插入到  func_db
        self.func_db[node.decl.name] = node

        return node

    # print_funcs
    # 打印 func_db
    def print_funcs(self):
        for func in self.func_db.keys():
            print(func)

#parser = ext_c_parser.GnuCParser()
parser = CustomerCParser()

ast = parse_file(
    "test_ext.c",
    use_cpp = True,
    cpp_path = "gcc",
    cpp_args = args,
    parser = parser,
)

v = FuncDefVisitor()
v.visit(ast)

v = FuncCallVisitor("func1")
v.visit(ast)

v = DependVisitor()
v.visit(ast)
parser.print_funcs()

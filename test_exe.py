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

args = [
    '-E'
]

parser = ext_c_parser.GnuCParser()
ast = parse_file(
    "test/main.c",
    use_cpp = True,
    cpp_path = "gcc",
    cpp_args = args,
    parser = parser,
)

from execute import execute, g_scope 

ast.ext.append(c_ast.FuncCall(name=c_ast.ID(name='main'),args=None))
execute(ast)

from pycparserext import ext_c_parser
from pycparser import parse_file

from pycparserext.ext_c_parser import TypeDeclExt

old_init = TypeDeclExt.__init__
def fixed_init(self, declname, quals, align, type, coord=None):
    old_init(self, declname, quals, align, type, coord)
    self.asm = None
TypeDeclExt.__init__ = fixed_init

args = [
    '-E'
]

ret = parse_file(
    "test_ext.c",
    use_cpp = True,
    cpp_path = "gcc",
    cpp_args = args,
    parser = ext_c_parser.GnuCParser(),
)

print(ret)
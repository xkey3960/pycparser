from __future__ import print_function
import sys

from pycparser import c_parser, c_ast, parse_file, c_generator

if __name__ == "__main__":
    print('start')
    filename = './TestPycparser.c'
    args = ['-E','-I/home/xkey/pycparser/utils/fake_libc_include/']
    ast = parse_file(filename, use_cpp=True, cpp_path='gcc', cpp_args=args)
    print(ast)
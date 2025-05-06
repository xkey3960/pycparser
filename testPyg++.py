from __future__ import print_function
import sys
import json

from pycparser import c_parser, c_ast, parse_file, c_generator

if __name__ == "__main__":
    print('start')
    filename = './TestPycparser.c'
    args = ['-E','-I/home/xkey/pycparser/utils/fake_libc_include/']
    ast = parse_file(filename, use_cpp=True, cpp_path='gcc', cpp_args=args)
    
    ast_dict = ast.to_dict()
    ast_str = json.dumps(ast_dict, indent=2)

    with open("parse_file.json", "w") as f:
        f.write(ast_str)
    print(ast_str)
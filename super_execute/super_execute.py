# Task(20261012-144135)

from pycparser.c_ast import (
    # Expressions
    Assignment, ID, BinaryOp, Constant,
)

def main():
    stmts = Assignment(op='=',
                       lvalue=ID('val2'),
                       rvalue=Constant(type='int', value='20')),
    print(stmts)
if __name__ == "__main__":
    main()
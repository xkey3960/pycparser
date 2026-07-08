#!/usr/bin/python

from pycparser.c_ast import Assignment, ID, BinaryOp, Constant

class Symbol():
    def __init__(self, name, value):
        self.name = name
        self.value = value

g_symbol_table = {
    "i": Symbol("i", 0)
}

class Execute():
    def __init__(self):
        pass
    def execute(self):
        pass

def execute(node):
    class_name = node.__class__.__name__
    if class_name in g_exe_class:
        return g_exe_class[class_name](node).execute()
    else:
        raise AssertionError(f"Unexpected AST node: '{class_name}'")

class ExeID(Execute):
    def __init__(self, id: ID):
        super().__init__()
        self.id = id
    def execute(self):
        if self.id.name in g_symbol_table:
            return g_symbol_table[self.id.name]
        else:
            raise AssertionError()

class ExeConstant(Execute):
    def __init__(self, constant:Constant):
        super().__init__()
        self.constant= constant
        self.type_force = {
            "int": int
        }

    def execute(self):
        if self.constant.type in self.type_force.keys():
            return self.type_force[self.constant.type](self.constant.value)
        else:
            raise AssertionError(f"Unexpected constant typpe: '{self.constant.type}'")

class ExeBinaryOp(Execute):
    def __init__(self, binary:BinaryOp):
        super().__init__()
        self.binary = binary
        self.funcs = {
            "+": self.add_execute,
            "-": self.sub_execute
        }
    def add_execute(self):
        return execute(self.binary.left) + execute(self.binary.right)
    def sub_execute(self):
        return execute(self.binary.left) - execute(self.binary.right)
    def execute(self):
        if self.binary.op in self.funcs:
            return self.funcs[self.binary.op]()
        else:
            raise AssertionError(f"Unexpected binary operation: '{self.binary.op}'")

class ExeAssignment(Execute):
    def __init__(self, assign:Assignment):
        super().__init__()
        self.assign = assign

    def execute(self):
        g_symbol_table[execute(self.assign.lvalue)].value = execute(self.assign.rvalue)
        return g_symbol_table[execute(self.assign.lvalue)].value

g_exe_class = {
        "ID" : ExeID,
        "Constant": ExeConstant,
        "Assignment": ExeAssignment,
        "BinaryOp": ExeBinaryOp,
    }

def main():
    print("hello")
    node_left = Constant(type="int", value="1")
    node_right = Constant(type="int", value="1")
    node_op = BinaryOp(op="+", left=node_left, right=node_right)
    node_value = Assignment(op="=", lvalue=ID("i"), rvalue=node_op)

    print(node_value)
    print(execute(node_value))

if __name__ == "__main__":
    main()


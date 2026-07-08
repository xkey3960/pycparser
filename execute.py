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
        return AssertionError()

class ExeID(Execute):
    def __init__(self, id: ID):
        super().__init__()
        self.id = id
    def execute(self):
        return g_symbol_table[self.id.name] if self.id.name in g_symbol_table else AssertionError()

class ExeConstant(Execute):
    def __init__(self, constant:Constant):
        super().__init__()
        self.constant= constant
        self.type_force = {
            "int": int
        }

    def execute(self):
        return self.type_force[self.constant.type](self.constant.value) \
                if self.constant.type in self.type_force.keys() \
                else AssertionError()

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
        return self.funcs[self.binary.op]() if self.binary.op in self.funcs else AssertionError()

class ExeAssignment(Execute):
    def __init__(self, assign:Assignment):
        super().__init__()
        self.assign = assign

    def execute(self):
        g_symbol_table[execute(self.assign.lvalue)] = execute(self.assign.rvalue)
        return g_symbol_table[execute(self.assign.lvalue)]

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


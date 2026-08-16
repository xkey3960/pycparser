"""端到端：用 CProgram 装载 test/main.c 并运行（多文件支持 S1）"""
from program import CProgram
from execute import g_scope

prog = CProgram(['test/main.c'])
prog.load()
prog.link()
result = prog.run()
print(f"main() = {result}")
print(g_scope)

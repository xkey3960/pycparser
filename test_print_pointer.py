import contextlib
import io

import execute as exe_mod
from program import CProgram

exe_mod.setup_global_scope()          # 重置 g_scope/g_functions（类型注册表全局保留）
files = ["test/printf_pointer.c"]
entry = "main"
prog = CProgram(files, entry=entry)
prog.load()
result = prog.run()                        # 不调用 link

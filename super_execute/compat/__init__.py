"""旧 API 的兼容壳（strangler 验证用）。

这个目录里放的是**顶层的** ``execute`` / ``program`` 模块，和仓库根那两个同名。
用法是把本目录放到 ``PYTHONPATH`` 最前面，于是 ``import program`` / ``import execute``
落到这里——旧测试文件一行都不用改，就能跑在新实现上：

    PYTHONPATH=super_execute/compat;super_execute;.  pytest test_program.py

注意顺序：``compat`` 必须在仓库根之前，否则会拿到旧的 ``program.py``。

这不是生产代码，唯一目的是**证明等价**：让旧的 264 个测试在新解释器上跑一遍，
看哪些过、哪些不过、为什么不过。跑通了就可以删旧 ``execute.py``；
跑不通的地方就是还缺的功能清单。
"""

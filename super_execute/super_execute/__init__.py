"""super_execute —— C 解释器的新实现（clean architecture 分层）。

只有 domain 层是纯 Python、零依赖；application / interface_adapters /
frameworks 会依赖它，反向不成立。
"""

__all__: list[str] = []

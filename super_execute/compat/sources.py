"""旧 ``sources`` 模块的兼容壳。

旧实现用 ``g_source_index`` 记录"每个源文件激活到哪一步了"（惰性装载的核心状态），
新实现没有这套机制——它装载即注册，错误延迟到使用。

这里只把**可观测的那部分**投影出来：某个文件被装载过就是 ``loaded``。
旧测试拿它断言"坏文件也被激活了但没有报错"，这个语义在新实现里同样成立。
"""

from __future__ import annotations

from typing import Any

import compat_state


class _SourceIndex:
    """``g_source_index.state`` 的替身：``{文件名: 'loaded'}``。"""

    @property
    def state(self) -> dict[str, str]:
        interpreter = compat_state.get_current()
        if interpreter is None:
            return {}
        return {name: "loaded" for name in interpreter.loaded_files()}

    def __str__(self) -> str:
        return str(self.state)


g_source_index = _SourceIndex()


def __getattr__(name: str) -> Any:
    raise AttributeError(f"module 'sources' has no attribute {name!r}")

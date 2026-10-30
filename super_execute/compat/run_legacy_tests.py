"""用新实现跑旧测试套件（strangler 的等价性验证）。

    py super_execute/compat/run_legacy_tests.py
    py super_execute/compat/run_legacy_tests.py test_program.py

**为什么不用 PYTHONPATH 影子替换**：pytest 在 prepend 导入模式下会把自己算出的
rootdir 插到 ``sys.path`` **最前面**，压过 ``PYTHONPATH``——于是 ``import program``
又拿回了仓库根那个旧模块，测出来的"全过"是假的（第一版就这么骗过我一次）。

所以这里改成：先用 importlib 按文件路径把兼容壳装进 ``sys.modules``，
再在**同一进程**里跑 pytest。``sys.modules`` 优先于任何路径搜索，
并且装完立刻断言 ``__file__`` 确实指向兼容壳。
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

COMPAT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = COMPAT_DIR.parent  # pycparser/super_execute
REPO_ROOT = PROJECT_ROOT.parent  # pycparser/

DEFAULT_TARGETS = [
    "test_program.py",
    "test_exe.py",
    "test_print_pointer.py",
    "test_qol2.py",
    "test_ext.py",
]


def install_compat() -> None:
    """按文件路径装载兼容壳，覆盖 sys.modules 里的同名模块。"""
    for path in (REPO_ROOT, PROJECT_ROOT, COMPAT_DIR):
        entry = str(path)
        if entry not in sys.path:
            sys.path.insert(0, entry)

    for name in ("execute", "program"):
        spec = importlib.util.spec_from_file_location(name, COMPAT_DIR / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)

    for name in ("execute", "program"):
        location = Path(sys.modules[name].__file__).resolve()
        assert location.parent == COMPAT_DIR, f"{name} 没有指向兼容壳: {location}"


def summarize(junit: Path) -> int:
    root = ET.parse(junit).getroot()
    suites = root.findall(".//testsuite") or [root]

    per_file: Counter = Counter()
    total: Counter = Counter()
    reasons: Counter = Counter()
    examples: dict[str, list[str]] = {}
    details: list[tuple[str, str]] = []

    for suite in suites:
        for case in suite.findall("testcase"):
            classname = case.get("classname", "")
            filename = classname.split(".")[0] + ".py" if classname else "?"
            label = f"{filename}::{case.get('name', '?')}"
            total[filename] += 1

            problem = case.find("failure")
            if problem is None:
                problem = case.find("error")
            if problem is None:
                per_file[filename] += 1
                continue

            lines = (problem.get("message") or "").strip().splitlines()
            first = lines[0] if lines else "?"
            traceback = problem.text or ""
            category = _category(first, traceback)
            reasons[category] += 1
            examples.setdefault(category, []).append(label)
            details.append((label, first))

    passed = sum(per_file.values())
    all_tests = sum(total.values())

    print("=" * 72)
    print("  旧测试套件 × 新实现（strangler 等价性验证）")
    print("=" * 72)
    print()
    print(f"  总计: {passed} passed / {all_tests} total")
    print()
    print("  按文件:")
    for filename in sorted(total):
        print(f"    {filename:<28} {per_file[filename]:>3} / {total[filename]:<3}")
    print()

    if reasons:
        print("  失败原因（按频次）:")
        for kind, count in reasons.most_common():
            print(f"    [{count:>2}] {kind}")
            for label in examples[kind][:2]:
                print(f"         e.g. {label}")
        print()

    print("  失败明细（前 30 条）:")
    for label, first in details[:30]:
        print(f"    {label}")
        print(f"        {first[:110]}")
    print()
    return all_tests - passed


def _reason(message: str) -> str:
    text = message.strip()
    if text.startswith("E "):
        text = text[2:]
    for separator in (":", "("):
        if separator in text:
            head = text.split(separator)[0].strip()
            if head and len(head) < 60:
                return head
    return text[:60]


#: 旧测试里直接断言旧内部结构的痕迹——这些断言在兼容层下没有意义，
#: 既不算通过也不算缺功能，单列一类。
_OLD_INTERNALS = (
    "g_source_index",
    "g_types",
    "g_static_",
    "g_call_stack",
    "g_current_file",
    "_func_names",
    "g_functions",
    "exe_mod.g_",
)


def _category(first: str, traceback: str) -> str:
    if any(marker in traceback for marker in _OLD_INTERNALS):
        return "断言旧内部结构（等价性无意义）"
    if "Unsupported" in first or "ParseError" in first:
        return "缺功能（未实现）"
    if first.startswith("assert") or "AssertionError" in first:
        return "语义 / 消息差异"
    return _reason(first)


def main(argv: list[str]) -> int:
    install_compat()

    targets = argv[1:] or DEFAULT_TARGETS
    junit = Path(tempfile.gettempdir()) / "legacy-compat.xml"
    if junit.exists():
        junit.unlink()

    import pytest

    pytest.main(["-q", "-p", "no:cacheprovider", f"--junitxml={junit}", *targets])
    if not junit.exists():
        print("pytest 没有产出 junit 报告")
        return 2
    return 0 if summarize(junit) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

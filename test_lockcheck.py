"""test_lockcheck.py — 持锁调用静态分析（LOCK-CHECK）

demo 工程 examples/lockcheck_demo/（多文件银行转账系统）埋点矩阵：

| 用例 | 形态 | 期望 |
|---|---|---|
| do_transfer      | 跨函数：transfer 持锁调 helper，helper 内 log_tx | 报 |
| audit_loop       | 循环内加锁→log_event | 报 |
| audit_balance    | 仅错误分支持锁→log_event | 报 |
| internal_bad     | callee 内部加锁→log_event（调用者无锁） | 报 |
| flush_batch      | 跨函数：worker_run 持锁调 helper | 报 |
| ledger_apply     | 加锁→解锁→再 log_tx | 不报 |
| audit_snapshot   | 加锁→干活→解锁→再 log_event | 不报 |
| reconcile / worker_report | 不持锁调 helper | 不报 |
| main             | 持锁调 ledger_total（内部自锁无日志） | 不报 |
| call_via_pointer | 函数指针调 log_event | 间接调用告警（不报违规） |

运行：py -X utf8 -m pytest test_lockcheck.py（Windows GBK 环境需 UTF-8 模式；
lockcheck 内部对 gcc 预处理输出做 UTF-8 解码兜底，测试断言不依赖运行编码）
"""

import glob
import os

import lockcheck

DEMO = os.path.join(os.path.dirname(__file__), 'examples', 'lockcheck_demo')


def demo_files():
    return sorted(glob.glob(os.path.join(DEMO, '*.c')))


def run_demo(**kw):
    kw.setdefault('acquire', ['mutex_lock'])
    kw.setdefault('release', ['mutex_unlock'])
    kw.setdefault('forbid', ['log_tx', 'log_event'])
    lc = lockcheck.LockCheck(demo_files(), **kw)
    lc.analyze()
    return lc


def violations(lc):
    return lc.summary()['violations']


def vkey(v):
    return (os.path.basename(v['file']), v['func'], v['forbidden'])


def test_planted_violations_all_found():
    """5 处埋点违规全部命中，且无多余报告（may-分析无漏报）。"""
    lc = run_demo()
    got = {vkey(v) for v in violations(lc)}
    want = {
        ('transfer.c', 'do_transfer', 'log_tx'),
        ('audit.c', 'audit_loop', 'log_event'),
        ('audit.c', 'audit_balance', 'log_event'),
        ('audit.c', 'internal_bad', 'log_event'),
        ('worker.c', 'flush_batch', 'log_tx'),
    }
    assert got == want


def test_clean_sites_not_reported():
    """干净模式（先解锁再记日志 / 不持锁调用）不产生误报。"""
    lc = run_demo()
    clean_funcs = {'ledger_apply', 'audit_snapshot', 'reconcile',
                   'worker_report', 'main', 'ledger_total',
                   'account_balance', 'call_via_pointer'}
    assert all(v['func'] not in clean_funcs for v in violations(lc))


def test_held_locks_traced():
    """违规报告的持锁列表含锁身份与获取来源。"""
    lc = run_demo()
    by_func = {v['func']: v for v in violations(lc)}
    ids = {lid for lid, _acq in by_func['do_transfer']['locks']}
    assert ids == {'&from->lock', '&to->lock'}
    ids2 = {lid for lid, _acq in by_func['audit_loop']['locks']}
    assert ids2 == {'&g_ledger.lock'}


def test_wrapper_propagation_without_config():
    """lock_ledger 不配表：摘要自动让调用者看到持锁（wrapper 覆盖）。"""
    lc = run_demo()
    v = {x['func']: x for x in violations(lc)}['internal_bad']
    assert ['&g_ledger.lock', '<callee:lock_ledger>'] in v['locks']


def test_indirect_call_warned_not_violation():
    """函数指针调用 → 间接调用告警（不假装 sound），不产生违规。"""
    lc = run_demo()
    files = {os.path.basename(item['file'])
             for item in lc.summary()['indirect_calls']}
    assert 'main.c' in files
    assert all(v['func'] != 'call_via_pointer' for v in violations(lc))


def test_unknown_forbidden_nothing_reported():
    """禁调表为空集时无违规（原语识别仍正常）。"""
    lc = run_demo(forbid=['no_such_func'])
    assert violations(lc) == []

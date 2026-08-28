/* audit.c — 审计子系统实现 */
#include "audit.h"
#include "ledger.h"
#include "common.h"

/* [违规-循环] 每轮迭代：加锁 → log_event → 解锁 */
void audit_loop(int n)
{
    int i;

    for (i = 0; i < n; i++) {
        lock_ledger();
        log_event("periodic-audit");
        unlock_ledger();
    }
}

/* [违规-分支] 仅当余额不符的错误分支持锁记日志 */
void audit_balance(int expected)
{
    int t = ledger_total();

    if (t != expected) {
        lock_ledger();
        log_event("balance-mismatch");
        unlock_ledger();
    }
}

/* 干净：加锁 → 干活（ledger_total 内部自锁，无日志）→ 解锁 → 再记日志 */
void audit_snapshot(void)
{
    lock_ledger();
    (void)ledger_total();
    unlock_ledger();
    log_event("snapshot-ok");
}

/* [违规-callee内部加锁] 本函数内部加锁后未解锁就记日志（调用者无锁） */
static void internal_bad(void)
{
    lock_ledger();
    log_event("internal-bad");
    unlock_ledger();
}

void run_internal_bad(void)
{
    internal_bad();
}

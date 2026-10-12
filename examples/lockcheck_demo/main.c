/* main.c — demo 入口：串起各子系统 + 函数指针边界用例 */
#include "common.h"
#include "ledger.h"
#include "transfer.h"
#include "audit.h"
#include "worker.h"

/* 通过函数指针调用 → 工具发出"间接调用未建模"告警（不假装 sound） */
static int call_via_pointer(void (*fn)(void))
{
    fn();
    return 0;
}

int main(void)
{
    /* 干净：main 持锁调 ledger_total（其内部自锁自解、无日志），不违规 */
    lock_ledger();
    (void)ledger_total();
    unlock_ledger();

    /* 违规路径（跨函数）：transfer 持锁 → do_transfer 内 log_tx */
    transfer(1, 2, 100);
    /* 干净路径：reconcile 不持锁 → 同函数无违规 */
    reconcile(3, 4, 50);

    audit_loop(3);       /* 违规（循环内持锁记日志） */
    audit_balance(1000); /* 违规（错误分支持锁记日志） */
    audit_snapshot();    /* 干净 */
    run_internal_bad();  /* 违规（callee 内部加锁记日志） */

    worker_run(5);       /* 违规（跨函数：持锁调 flush_batch） */
    worker_report(2);    /* 干净 */

    /* 函数指针：把禁调函数当回调传 → 间接调用告警 */
    call_via_pointer(log_event);
    return 0;
}

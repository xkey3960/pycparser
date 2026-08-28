/* ledger.c — 台账子系统实现 */
#include "ledger.h"
#include "common.h"

struct ledger g_ledger = { 0, MUTEX_INIT };

/* wrapper：acquire 语义由摘要传播（adds = {&g_ledger.lock}） */
void lock_ledger(void)
{
    mutex_lock(&g_ledger.lock);
}

/* wrapper：release 语义由摘要传播（rels 移除调用者持有的该锁） */
void unlock_ledger(void)
{
    mutex_unlock(&g_ledger.lock);
}

int ledger_total(void)
{
    int t;

    lock_ledger();
    t = g_ledger.total;
    unlock_ledger();
    return t;
}

int ledger_apply(const char *who, int delta)
{
    int newv;

    lock_ledger();
    g_ledger.total += delta;
    newv = g_ledger.total;
    unlock_ledger();

    /* 干净：已解锁再记日志，不违规 */
    log_tx(who, delta);
    return newv;
}

/* worker.c — 工作线程子系统实现 */
#include "worker.h"
#include "ledger.h"
#include "common.h"

/* 批次结果写日志。规则：**不得持锁进入**。
   违规点在此处 log_tx —— worker_run 持锁调用 flush_batch 时状态非空 */
void flush_batch(int n)
{
    log_tx("worker", n);
}

/* [违规-跨函数] 持锁调 flush_batch */
void worker_run(int jobs)
{
    lock_ledger();
    g_ledger.total += jobs;
    flush_batch(jobs);
    unlock_ledger();
}

/* 干净对照：不持锁调用 flush_batch */
void worker_report(int jobs)
{
    flush_batch(jobs);
}

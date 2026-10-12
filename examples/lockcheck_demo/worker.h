/* worker.h — 工作线程子系统 */
#ifndef LOCKCHECK_DEMO_WORKER_H
#define LOCKCHECK_DEMO_WORKER_H

/* 工作线程入口：持台账锁期间 flush_batch → 其内 log_tx 违规 */
void worker_run(int jobs);

/* 干净对照：不持锁调用 flush_batch */
void worker_report(int jobs);

#endif /* LOCKCHECK_DEMO_WORKER_H */

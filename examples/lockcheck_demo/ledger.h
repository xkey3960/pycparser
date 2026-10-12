/* ledger.h — 台账子系统（全局台账锁 wrapper） */
#ifndef LOCKCHECK_DEMO_LEDGER_H
#define LOCKCHECK_DEMO_LEDGER_H

/* 加锁/解锁 wrapper：内部调 mutex_lock/mutex_unlock。
   工具无需把 wrapper 配表——跨函数摘要自动让调用者看到锁被持有/释放 */
void lock_ledger(void);
void unlock_ledger(void);

/* 查询台账总额（内部自锁，安全） */
int ledger_total(void);

/* 应用一笔台账变更：先锁后改再解锁，**解锁后**才记日志（干净模式） */
int ledger_apply(const char *who, int delta);

#endif /* LOCKCHECK_DEMO_LEDGER_H */

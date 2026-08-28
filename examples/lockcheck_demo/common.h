/* common.h — 锁原语抽象 + 禁调函数声明（LOCK-CHECK demo 公共头） */
#ifndef LOCKCHECK_DEMO_COMMON_H
#define LOCKCHECK_DEMO_COMMON_H

/* 极简 mutex 抽象：本工程仅做静态分析演示，不真正执行，
   工具只按函数名识别加锁/解锁原语 */
typedef int mutex_t;
#define MUTEX_INIT 0

void mutex_lock(mutex_t *m);
void mutex_unlock(mutex_t *m);

/* ============ 禁调函数（规则：不允许在持有任何锁时调用） ============ */

/* 交易日志：内部有磁盘 IO / 网络，持锁调用会导致死锁或性能劣化 */
void log_tx(const char *who, int amount);

/* 审计事件日志：同上，禁调 */
void log_event(const char *msg);

/* ============ 业务结构 ============ */

struct ledger {
    int total;
    mutex_t lock;
};

extern struct ledger g_ledger;

#endif /* LOCKCHECK_DEMO_COMMON_H */

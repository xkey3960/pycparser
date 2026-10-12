/* audit.h — 审计子系统 */
#ifndef LOCKCHECK_DEMO_AUDIT_H
#define LOCKCHECK_DEMO_AUDIT_H

/* [违规-循环] 循环体内加锁后记日志 */
void audit_loop(int n);

/* [违规-分支] 仅错误分支持锁记日志 */
void audit_balance(int expected);

/* 干净：加锁干活→解锁→再记日志 */
void audit_snapshot(void);

/* [违规-callee内部加锁] 被调函数内部加锁后记日志（调用者无锁） */
void run_internal_bad(void);

#endif /* LOCKCHECK_DEMO_AUDIT_H */

/* transfer.h — 转账子系统 */
#ifndef LOCKCHECK_DEMO_TRANSFER_H
#define LOCKCHECK_DEMO_TRANSFER_H

/* 转账：加两账户锁后调用 do_transfer（do_transfer 内部记日志 → 违规） */
void transfer(int from_id, int to_id, int amount);

/* 对账：不持锁调用 do_transfer（干净对照） */
void reconcile(int from_id, int to_id, int amount);

#endif /* LOCKCHECK_DEMO_TRANSFER_H */

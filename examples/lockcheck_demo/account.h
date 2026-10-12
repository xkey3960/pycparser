/* account.h — 账户子系统（每账户一把锁，宏内联加锁） */
#ifndef LOCKCHECK_DEMO_ACCOUNT_H
#define LOCKCHECK_DEMO_ACCOUNT_H

#include "common.h"

#define MAX_ACCOUNTS 16

typedef struct account {
    int id;
    int balance;
    mutex_t lock;
} account_t;

account_t *get_account(int id);

/* 宏内联加锁：预处理后锁身份为 &(a)->lock 的具体表达式 */
#define lock_account(a)   mutex_lock(&(a)->lock)
#define unlock_account(a) mutex_unlock(&(a)->lock)

int account_balance(account_t *a);

#endif /* LOCKCHECK_DEMO_ACCOUNT_H */

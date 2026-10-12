/* account.c — 账户子系统实现 */
#include "account.h"

static account_t g_accounts[MAX_ACCOUNTS];

account_t *get_account(int id)
{
    if (id < 0 || id >= MAX_ACCOUNTS) {
        return 0;
    }
    return &g_accounts[id];
}

int account_balance(account_t *a)
{
    int b;

    lock_account(a);
    b = a->balance;
    unlock_account(a);
    return b;
}

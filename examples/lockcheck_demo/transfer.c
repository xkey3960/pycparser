/* transfer.c — 转账子系统实现 */
#include "transfer.h"
#include "account.h"
#include "common.h"

/* 内部辅助：搬钱并记交易日志。规则：**不得持锁进入**。
   违规点实际在此处 log_tx —— 工具经 transfer() 持锁调用传播到这里的
   状态非空，即报告（锁溯源到 transfer() 的加锁处） */
static void do_transfer(account_t *from, account_t *to, int amount)
{
    from->balance -= amount;
    to->balance += amount;
    log_tx("transfer", amount);
}

/* [违规-跨函数] 持锁调用 do_transfer → 其内 log_tx 持锁执行 */
void transfer(int from_id, int to_id, int amount)
{
    account_t *from = get_account(from_id);
    account_t *to = get_account(to_id);

    if (from == 0 || to == 0) {
        return;
    }
    lock_account(from);
    lock_account(to);
    do_transfer(from, to, amount);
    unlock_account(to);
    unlock_account(from);
}

/* 干净对照：不持锁调用 do_transfer → 不违规 */
void reconcile(int from_id, int to_id, int amount)
{
    account_t *from = get_account(from_id);
    account_t *to = get_account(to_id);

    if (from == 0 || to == 0) {
        return;
    }
    do_transfer(from, to, amount);
}

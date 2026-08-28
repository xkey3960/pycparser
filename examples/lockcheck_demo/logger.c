/* logger.c — 禁调函数的实现（持锁调用是违规，实现本身无锁逻辑） */
#include "common.h"
#include <stdio.h>

void log_tx(const char *who, int amount)
{
    printf("[tx] %s %+d\n", who, amount);
}

void log_event(const char *msg)
{
    printf("[event] %s\n", msg);
}

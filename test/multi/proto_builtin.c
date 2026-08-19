#include "proto_builtin.h"
char *p;
int main(void)
{
    p = (char*)malloc(8);
    memset(p, 65, 3);          /* 原型遮蔽内置？ */
    return (int)*(p + 1);       /* 65（堆字节读取） */
}

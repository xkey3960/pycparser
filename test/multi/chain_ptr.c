/* 复现 test/printf_pointer.c 的链式指针场景（&p->member 成员地址）：
   typedef 链 + 自引用指针 + 成员地址赋值 + 指针复制 + -> 访问。 */
#define NULL 0

typedef struct tagAAA {
    struct tagAAA *pstNext;
} AAA;
typedef struct tagBBB {
    AAA *pstAAA;
} BBB;
typedef struct tagCCC {
    AAA stAAA;
} CCC;

int main(void)
{
    AAA *pa = NULL;
    BBB b;
    CCC c;
    CCC *pc = &c;

    b.pstAAA = &pc->stAAA;    /* &(p->member)：成员地址（MEM-1 修复） */
    pa = b.pstAAA;            /* 指针复制 */
    pa = pa->pstNext;         /* 自引用指针访问（NULL→0） */
    return (pa == NULL) ? 7 : 0;   /* pa 未初始化=0（NULL）→ 7 */
}

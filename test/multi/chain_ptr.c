/* 复现 test/printf_pointer.c 链式指针 + 强转场景：
   (AAA*)pc 强转（CCC* → AAA*）后解引用 → 按首成员 reinterpret（AAA 是 CCC 首成员）。 */
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

    b.pstAAA = (AAA *)pc;       /* 强转：CCC* → AAA* */
    pa = b.pstAAA;              /* 指针复制 */
    pa = pa->pstNext;           /* 按 AAA 解释 c 首成员 stAAA，读 pstNext（NULL→0） */
    return (pa == NULL) ? 7 : 0;
}

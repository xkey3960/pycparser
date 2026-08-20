#define NULL 0

typedef struct tagAAA{
    struct tagAAA *pstNext;
}AAA;
typedef struct tagBBB{
    AAA *pstAAA;
}BBB;
typedef struct tagCCC{
    AAA stAAA;
}CCC;
int main()
{
    AAA *pa = NULL;
    BBB b;
    CCC c;
    CCC *pc = &c;

    b.pstAAA = (AAA *)pc;
    pa = b.pstAAA;
    pa = pa->pstNext;
}

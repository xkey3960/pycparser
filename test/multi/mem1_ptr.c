
struct AAA { int x; int y; };
int main(void) {
    /* ① 标量写回（之前做不到） */
    int x = 0;
    int *p = &x;
    *p = 5;
    int a = x;                    /* 5 */
    /* ② 指针算术按元素大小 + p[i] + 写 */
    int arr[3];
    arr[0] = 10; arr[1] = 20; arr[2] = 30;
    int *q = &arr[0];
    int *r = q + 1;               /* int* → 偏移 4 字节 */
    int b = *r;                   /* 20 */
    int c = q[2];                 /* 30 */
    *(q + 1) = 99;                /* arr[1] = 99 */
    /* ③ p++ 步长 + 指针比较 */
    int *s = &arr[0];
    int eq = (s == &arr[0]);      /* 1 */
    int ne = (s == &arr[1]);      /* 0 */
    s++;
    int d = *s;                   /* 99（arr[1] 被写） */
    /* ④ -> 写 struct 成员（经 Address） */
    struct AAA o; o.x = 1; o.y = 2;
    struct AAA *po = &o;
    po->x = 100;
    int e = o.x;                  /* 100 */
    /* ⑤ &(p->member) 成员地址（printf_pointer 场景：&pc->stAAA） */
    struct AAA inner; inner.x = 6;
    struct AAA *pin = &inner;
    struct AAA *alias2 = &inner;
    alias2 = pin;                 /* 指针复制 */
    int f = alias2->x;            /* 6 */
    return a + b + c + arr[1] + eq + (1 - ne) + d + e + f;   /* 355 + 6 = 361 */
}

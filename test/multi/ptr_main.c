
struct AAA { int x; int y; };
int main(void) {
    struct AAA a;
    a.x = 5;
    a.y = 37;
    struct AAA *pa = &a;
    pa->x = 99;              /* 经指针写回 a（StructValue 引用共享） */
    int via_ptr = pa->y;     /* 经指针读 */
    return a.x + via_ptr;    /* 99 + 37 = 136 */
}

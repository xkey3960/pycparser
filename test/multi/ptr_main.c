
struct AAA { int x; int y; };
int main(void) {
    struct AAA a;
    a.x = 5;
    a.y = 37;
    struct AAA *pa = &a;
    pa->x = 99;              /* 经指针写回 a（StructValue 引用共享） */
    int via_ptr = pa->y;     /* 经指针读 */
    int arr[2];
    arr[0] = 7;
    arr[1] = 8;
    int *p = &arr[0];        /* 数组元素地址 */
    int *q = p + 1;          /* 指针算术：宽松退化（MEM-1 前） */
    return (a.x + via_ptr) + (*p + *q);   /* (99+37) + (7+8) = 151 */
}

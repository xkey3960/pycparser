
double half(double x) { return x / 2; }
int trunc_int(void) { return 3.7; }          /* 返回转换 → 3 */
int main(void) {
    char c = 5;
    short s = 3;
    int a = sizeof(c + 1);                    /* 整数提升 char→int → 4 */
    int b = sizeof(s + s);                    /* 提升 short→int → 4 */
    double d = 1 + 2.5;                       /* int+double → double 3.5 */
    int x = 3.7;                              /* 赋值转换 → 3 */
    int h = (int)(half(5) * 4);               /* 参数 int→double：5.0/2=2.5 → 10 */
    int t = trunc_int();                      /* 返回转换 → 3 */
    int y = 5;
    y += 2.7;                                 /* 复合赋值 → 7 */
    return (a + b) + (int)(d * 2) + x + h + t + y;   /* 8 + 7 + 3 + 10 + 3 + 7 = 38 */
}


int inc(int x) { return x + 1; }
int dbl(int x) { return x * 2; }
int apply(int (*fp)(int), int x) { return fp(x); }
int main(void) {
    int (*fp)(int);
    fp = inc;
    int a = fp(41);              /* 42（经变量调用） */
    fp = dbl;
    int b = fp(21);              /* 42 */
    fp = &inc;
    int c = fp(9);               /* 10 */
    return a + b + c + apply(inc, 41);   /* 94 + 42 = 136 */
}

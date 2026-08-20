
int inner(int a) {
    return a + zz;               /* 第 3 行：未定义 zz */
}
int helper(int x) {
    return inner(x) + 1;         /* 第 6 行调用 */
}
int main(void) {
    return helper(5);            /* 第 9 行调用 */
}

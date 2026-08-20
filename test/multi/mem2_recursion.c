
int count = 0;
int fact(int n) { if (n <= 1) return 1; return n * fact(n - 1); }
int is_odd(int n);
int is_even(int n) { if (n == 0) return 1; return is_odd(n - 1); }
int is_odd(int n) { if (n == 0) return 0; return is_even(n - 1); }
int helper(int n) {
    int t = 100;                 /* 每帧局部变量独立（递归+遮蔽） */
    if (n == 0) return t;
    return helper(n - 1) + 1;
}
void bump(int n) { if (n == 0) return; count++; bump(n - 1); }
int main(void) {
    bump(10);                    /* 递归写全局 count → 10 */
    return fact(5) + is_even(10) + helper(5) + count;   /* 120+1+105+10 = 236 */
}


#include <setjmp.h>
jmp_buf env;
int level3(void) { longjmp(env, 7); return 0; }
int level2(void) { return level3(); }
int level1(void) { return level2(); }
int main(void) {
    int got = 0;
    if (setjmp(env) == 0) {
        level1();
    } else {
        got = 1;
    }
    return got;            /* 跨 3 层跳回 -> 1 */
}

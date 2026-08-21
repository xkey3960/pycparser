
#include <setjmp.h>
jmp_buf env;
int deep(void) { longjmp(env, 42); return 0; }
int main(void) {
    int r;
    if (setjmp(env) == 0) {
        r = 1;
        deep();
    } else {
        r = 2;
    }
    return r;              /* longjmp 后 r=2 */
}

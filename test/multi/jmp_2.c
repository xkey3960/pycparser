
#include <setjmp.h>
jmp_buf env;
int main(void) {
    int v = setjmp(env);
    if (v == 0) {
        longjmp(env, 99);
        return 0;
    }
    return v;              /* setjmp ¶þ´Î·µ»Ø 99 */
}

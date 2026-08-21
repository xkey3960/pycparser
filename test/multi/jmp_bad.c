#include <setjmp.h>
jmp_buf env;
int main(void) { longjmp(env, 1); return 0; }

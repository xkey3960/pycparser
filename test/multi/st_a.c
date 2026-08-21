static int helper(void) { return 10; }
static int g = 100;
int use_a(void) { g += 1; return helper() + g; }   /* 10 + 101 = 111 */

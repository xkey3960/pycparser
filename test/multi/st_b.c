static int helper(void) { return 20; }
static int g = 200;
int use_b(void) { g += 5; return helper() + g; }   /* 20 + 205 = 225 */

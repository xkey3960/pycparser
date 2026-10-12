struct Pt { int x; int y; };
int helper(int a, struct Pt p);
int main(void) {
    struct Pt p; p.x = 10; p.y = 20;
    return helper(27, p);      /* 27+10+20 = 57 */
}

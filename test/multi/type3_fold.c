
enum Color { RED, GREEN, BLUE };
int pick(int x) {
    switch (x) {
        case 1 + 2: return 10;       /* 折叠为 3 */
        case GREEN: return 20;       /* 枚举常量 1 */
        case 'A': return 30;         /* 字符 65 */
        default: return 99;
    }
}
int rng(int x) {
    switch (x) {
        case 1 ... 5: return 1;      /* case range */
        default: return 0;
    }
}
struct Bits { int a : 4 + 4; int b : 3; };   /* 位域宽度折叠 4+4 → 8 */
int main(void) {
    return pick(3) + pick(1) + pick(65) + pick(9) + rng(3) + rng(9)
           + sizeof(struct Bits);    /* 10+20+30+99 + 1+0 + 8 = 168 */
}

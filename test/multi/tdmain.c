/* 与 tdlib.c 相同的 typedef 链（模拟共享头）：应静默去重 */
typedef int Base;
typedef Base Mid;

int get_mid(void);

int main()
{
    Mid m;
    m = 3;
    return get_mid() + m;   /* 7 + 3 = 10 */
}

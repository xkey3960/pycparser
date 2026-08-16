/* 与 e2e_lib.c 相同的类型（模拟共享头）：跨文件静默去重 */
typedef struct Point {
    int x;
    int y;
} Point;

typedef enum Color {
    RED,
    GREEN,
    BLUE
} Color;

Point make_point(int x, int y);
int point_sum(Point p);
int color_value(Color c);

int main()
{
    Point p = make_point(10, 5);   /* 跨文件 struct 返回值 */
    Point q = p;                    /* 值拷贝 */
    q.x = 100;                      /* 不影响 p */
    return color_value(GREEN) + point_sum(p) + q.x;
    /* GREEN=1 + (10+5) + 100 = 116 */
}

/* 与 e2e_lib.c 相同的类型（模拟共享头）：跨文件静默去重 */
typedef struct Point {
    int x;
    int y;
} Point;

int point_sum(Point p)
{
    return p.x + p.y;
}

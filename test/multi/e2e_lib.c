typedef enum Color {
    RED,
    GREEN,
    BLUE
} Color;

typedef struct Point {
    int x;
    int y;
} Point;

int color_value(Color c)
{
    return c;
}

Point make_point(int x, int y)
{
    Point p;
    p.x = x;
    p.y = y;
    return p;
}

struct Point {
    int x;
    int y;
};

int manhattan(struct Point p)
{
    int ax = p.x < 0 ? -p.x : p.x;
    int ay = p.y < 0 ? -p.y : p.y;
    return ax + ay;
}

int cost(int step)
{
    switch (step) {
        case 0: return 1;
        case 1: return 1;
        case 2: return 2;
        default: return 10;
    }
}

int main(void)
{
    struct Point path[3] = {
        { 1, -2 },
        { -3, 4 },
        { 5, 6 },
    };

    int total = 0;
    for (int i = 0; i < 3; i++) {
        total += manhattan(path[i]) + cost(i);
    }
    struct Point *pstPoint = (struct Point *)malloc(sizeof(struct Point));
    pstPoint->x = 1;
    pstPoint->y = 2;
    printf("%u\n", pstPoint->x);
    return total;
}

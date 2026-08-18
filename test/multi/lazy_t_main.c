int sum_pt(struct Pt p);

int main(void)
{
    struct Pt p;      /* struct Pt 定义在另一文件（lazy_t.c） */
    p.x = 3;
    p.y = 4;
    return sum_pt(p); /* 3 + 4 = 7 */
}

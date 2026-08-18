int color_val(void);

int main(void)
{
    enum EColor c;      /* enum EColor 定义在另一文件（lazy_e.c） */
    c = EGREEN;
    return color_val() + c;   /* 1 + 1 = 2 */
}

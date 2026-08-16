int helper_gv(void);

int g = helper_gv();   /* 全局变量 init 调另一文件的函数（P5） */

int main(void)
{
    return g;
}

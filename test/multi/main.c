/* 跨文件引用：类型与函数声明（模拟共享头文件内容） */
typedef struct Pt {
    int x;
    int y;
} Pt;

int helper(void);
int sum_pt(Pt p);

int main()
{
    Pt p;
    p.x = 10;
    p.y = 5;
    return helper() + sum_pt(p);
}

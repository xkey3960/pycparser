/* struct ZZMissing 在任何文件都无定义 → 惰性激活后仍找不到 → 成员访问报错 */
int main(void)
{
    struct ZZMissing m;
    m.v = 1;
    return m.v;
}

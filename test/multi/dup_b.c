int dupf(void)   /* 与 dup_a.c 重复定义（非 static 非入口）→ 报错 */
{
    return 2;
}

int main(void)
{
    return 1;
}

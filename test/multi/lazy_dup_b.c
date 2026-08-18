int dupf(void)   /* 与 lazy_dup_a.c 重复定义（非 static 非入口，激活时报错） */
{
    return 2;
}

int b_func(void)
{
    return 0;
}

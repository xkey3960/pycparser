/* L4 夹具：struct L4Dup 重定义（成员 y，与 a 文件不同）→ 用时才检冲突。 */
struct L4Dup {
    double y;
};

int l4_dup_b(void)
{
    return 2;
}

/* L4 夹具：struct L4Dup 定义（成员 x）；main 不用它时不应触发重定义冲突。 */
struct L4Dup {
    int x;
};

int l4_dup_a(void)
{
    return 1;
}

/* L4 夹具：main 真正使用坏 struct（sizeof）→ 用时才检（报错）。 */
typedef struct L4BadUse {
    int arr[no_such_thing_l4use + 1];
} L4BadUse;

int main(void)
{
    return sizeof(struct L4BadUse);
}

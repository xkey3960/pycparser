/* 含类型错误/未定义符号的文件：惰性模式下 main 不引用它 → 不应被激活 */
typedef struct Bad {
    int arr[no_such_thing + 1];
} Bad;

int bad_func(void)
{
    return no_such_thing;
}

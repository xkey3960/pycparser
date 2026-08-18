/* L4 夹具：文件含"坏" struct（数组维度引用未定义符号），但 main 只用正常函数。
   验证：启动装载（activate_all）不检查类型 —— 坏 struct 激活也不报错。 */
typedef struct L4Bad {
    int arr[no_such_thing_l4 + 1];
} L4Bad;

int l4_ok(void)
{
    return 7;
}

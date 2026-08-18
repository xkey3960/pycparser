/* L4 夹具：main 调用正常函数 l4_ok（定义在 lazy4_bad.c，该文件另含坏 struct）。
   验证：激活 lazy4_bad.c 时坏 struct 只注册不布局 → 不报错。 */
int l4_ok(void);

int main(void)
{
    return l4_ok() + 35;   /* 7 + 35 = 42 */
}

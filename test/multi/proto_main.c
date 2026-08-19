/* 原型声明文件 + 定义文件分离：main 只用原型，定义在 impl 文件。
   验证原型注册签名占位、惰性激活拿到定义后正常调用。 */
struct a;
int func(struct a a1);

int main(void)
{
    struct a x;
    x.aaa = 21;
    return func(x);
}

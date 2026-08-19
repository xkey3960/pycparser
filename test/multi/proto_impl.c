/* func 定义文件（与 proto_decl.c 的原型对应）。 */
struct a {
    int aaa;
};

int func(struct a a1)
{
    return a1.aaa * 2;
}

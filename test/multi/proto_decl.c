/* 原型声明文件（对应上游 tests/two_decl.c 形态）：
   前置声明 + 函数原型（按值传不完整类型）+ 后置完整定义。 */
struct a;

int func(struct a a1);

struct a {
    int aaa;
};

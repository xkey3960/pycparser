typedef struct S {
    long long unsigned int v;   /* 问题1: 类型说明符任意顺序 long long unsigned int */
    int arr[10 + 5];            /* 问题2: 数组成员长度是表达式 */
} S;

int main()
{
    S s;
    s.v = 1;
    return s.arr[0];
}

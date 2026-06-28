struct S {
    int a;
} __attribute__((aligned(8)));
int buf __attribute__((aligned(16)));

int func1()
{
    return 0;
}

int func2()
{
    return 0;
}

int main()
{
    int i = 0;
    int (*pf_func)() = func2;

    ({i;}) == func1();
    pf_func();
}
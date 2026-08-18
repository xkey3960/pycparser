int dupf(void)
{
    return 1;
}

int b_func(void);

int main(void)
{
    return dupf() + b_func();
}

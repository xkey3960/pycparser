
#include <stdarg.h>

int sum(int n, ...)
{
    va_list ap;
    va_start(ap, n);
    int total = 0;
    for (int i = 0; i < n; i++)
        total += va_arg(ap, int);
    va_end(ap);
    return total;
}

int inner(int a, ...)
{
    va_list ap;
    va_start(ap, a);
    int v = va_arg(ap, int);
    va_end(ap);
    return v;
}

int outer(int n, ...)
{
    va_list ap;
    va_start(ap, n);
    int a = va_arg(ap, int);
    int b = inner(1, 100);        /* 嵌套调用：不应破坏外层 va */
    int c = va_arg(ap, int);
    va_end(ap);
    return a + b + c;
}

int main(void)
{
    return sum(3, 10, 20, 12) + outer(2, 11, 22) - 133;   /* 42 + 133 - 133 = 42 */
}

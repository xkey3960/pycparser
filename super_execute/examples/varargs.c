typedef int va_list;

int sum(int n, ...)
{
    va_list ap;
    int total = 0;
    va_start(ap, n);
    for (int i = 0; i < n; i++)
        total += va_arg(ap, int);
    va_end(ap);
    return total;
}

int grade(int score)
{
    switch (score) {
        case 90 ... 100: return 4;
        case 80 ... 89:  return 3;
        case 60 ... 79:  return 2;
        default:         return 0;
    }
}

int main(void)
{
    typeof(int) bonus = ({ int t = sum(2, 5, 6); t * 2; });

    printf("sum   = %d\n", sum(3, 1, 2, 3));
    printf("bonus = %d\n", bonus);
    printf("grade = %d\n", grade(85));

    return bonus + grade(85);
}

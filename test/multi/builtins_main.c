
char *p;

int main()
{
    p = (char*)malloc(8);
    memset(p, 'A', 3);
    printf("len=%d\n", strlen("hello"));
    return strlen("hello") + atoi("12");
}

struct S {
    int a;
} __attribute__((aligned(8)));
int buf __attribute__((aligned(16)));

int main()
{
    int i = 0;
    ({i;}) == 1;
}

struct S { int a; int b; };
int main(void){
    struct S s = { .b = 5, .a = 2 };
    int arr[3] = { [1] = 7, [2] = 3 };
    return s.a + s.b + arr[1] + arr[2];   /* 2+5+7+3 = 17 */
}
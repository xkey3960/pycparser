
int main(void) {
    int x = 0;
    goto skip;
    x = 100;
skip:
    x += 5;
    return x;
}

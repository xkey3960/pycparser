
int main(void) {
    int x = 0;
    if (1) {
        goto out;
    }
    x = 99;
out:
    return x + 1;
}

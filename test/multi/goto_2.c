
int main(void) {
    int i;
    for (i = 0; i < 100; i++) {
        if (i == 7) goto done;
    }
done:
    return i;
}

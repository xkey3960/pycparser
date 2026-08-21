typedef struct BadR { int arr[no_such_r + 1]; } BadR;
int use_bad(void) { return sizeof(struct BadR); }

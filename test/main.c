typedef struct tagTmp{
    int id;
    char acName[10];
} TmpStruct_S;

int main()
{
    TmpStruct_S x;
    x.id = 100;
    TmpStruct_S y = x;   // 值拷贝：y.id = 100
    x.id = 200;          // 不影响 y
    return y.id;         // 期望 100
}

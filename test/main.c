typedef struct tagTmp{
    int id;
    char acName[10];
} TmpStruct_S;

typedef union tagVal{
    char c;
    int i;
} Val_U;

int main()
{
    TmpStruct_S x;
    x.id = 100;
    TmpStruct_S y = x;   // 值拷贝：y.id = 100
    x.id = 200;          // 不影响 y
    Val_U v;
    v.i = 65;            // union 活跃成员写入
    return y.id + v.i;   // 100 + 65 = 165
}

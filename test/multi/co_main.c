
#define offsetof(TYPE, MEMBER) ((unsigned long) &((TYPE *)0)->MEMBER)
#define container_of(ptr, type, member) ({              \
    const typeof( ((type *)0)->member ) *__mptr = (ptr); \
    (type *)( (char *)__mptr - offsetof(type, member) );})

struct Node { int value; struct Node *next; };
struct List { struct Node node; int count; };
int main(void) {
    struct List list;
    list.node.value = 42;
    list.count = 7;
    struct Node *np = &list.node;
    struct List *lp = container_of(np, struct List, node);
    /* 通过 container_of 从 Node 指针找回宿主 List：读 value 与 count */
    return lp->count * 10 + lp->node.value / 42;   /* 7*10 + 1 = 71 */
}

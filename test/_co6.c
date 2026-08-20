
#define offsetof(TYPE, MEMBER) ((unsigned long) &((TYPE *)0)->MEMBER)
#define container_of(ptr, type, member) ({              \
    const typeof( ((type *)0)->member ) *__mptr = (ptr); \
    (type *)( (char *)__mptr - offsetof(type, member) );})

struct Node { int value; struct Node *next; };
struct List { struct Node node; int count; };
int main(void) {
    struct List list;
    list.count = 7;
    struct Node *np = &list.node;
    struct List *lp = container_of(np, struct List, node);
    return lp->count;
}

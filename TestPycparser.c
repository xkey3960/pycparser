void printArray()
{
    int iLoop = 0;
    int iTest = 0;

    // for (iLoop = 0; iLoop<10; (void)({iLoop++;iTest=iLoop;}))
    // {
    //     iLoop;
    // }
}

int main(int argc, char *argv[])
{
    int x = ({int y = 1; y+1; });
    printArray();
    return 0;
}
void printArray()
{
    int iLoop = 0;
    int iTest = 0;

    for (iLoop = 0; iLoop<10; (void)({iLoop++;iTest=iLoop;}))
    {
        iLoop;
    }
}

int main(int argc, char *argv[])
{
    printArray();
    return 0;
}
int main(int argc, char *argv[])
{
    int iLoop = 0;
    int iTest = 0;
    int x = ({int y = 1; y++;});
    for (iLoop = 0; iLoop<10; (void)({iLoop++;iTest=iLoop;}))
    {
        iLoop;
    }
    return 0;
}
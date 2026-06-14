int main() {
  int x = ({int y = 1; y++;});
  for (int iLoop = 0; iLoop<10; (void)({x++;}))
  {
    (void)(x++);
  }
  return 0;
}

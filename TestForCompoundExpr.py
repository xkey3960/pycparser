from pycparser import c_lexer

# 创建哑回调函数（若不需要实际功能）
def dummy_error_func(msg, line, column):
    pass

def dummy_on_lbrace_func():
    pass

def dummy_on_rbrace_func():
    pass

def dummy_type_lookup_func(typname):
    return None

# 初始化 lexer
lexer = c_lexer.CLexer(
    error_func=dummy_error_func,
    on_lbrace_func=dummy_on_lbrace_func,
    on_rbrace_func=dummy_on_rbrace_func,
    type_lookup_func=dummy_type_lookup_func
)
lexer.build()
lexer.input('for (iLoop = 0; iLoop<10; (void)({iLoop++;iTest=iLoop;}))')
# 正确获取 Token 流
while True:
    tok = lexer.lexer.token()  # 通过 lexer.lexer.token() 访问 PLY 生成的 Token
    if not tok:
        break
    print(f"Type: {tok.type}, Value: {tok.value}")
"""接口适配层：把外面的世界翻译成用例能吃的形状。

目前只有一种输入：pycparser 的 C AST。适配器负责

    AST 声明符  → CType        （type_builder）
    AST 顶层声明 → 用例调用     （declaration_loader）

它依赖 ``pycparser``（框架）与 ``application``（用例），反向不成立——
所以将来换成自研 parser 或 Clang AST，只换这一层。
"""

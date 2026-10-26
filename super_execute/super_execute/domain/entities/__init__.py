"""领域实体：作用域、命名空间、符号。

实体与值对象的界线：实体有身份（`Scope.scope_id`、符号的名字）并且可以被
引用；值对象按值相等（`Address`）。这里全部是实体，值对象在
``super_execute.domain.value_objects``。
"""

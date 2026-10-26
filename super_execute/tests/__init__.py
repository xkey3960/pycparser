"""super_execute 的测试。

按 clean architecture 的分层组织：``unit/domain``、``unit/application``（待建）、
``integration``（待建）。测试目录带 ``__init__.py``，这样 pytest 的 prepend
导入模式会把包根 ``super_execute/`` 放进 sys.path，``import super_execute`` 才能解析。
"""

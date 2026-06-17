"""Placeholder — content split into themed files.

The tests that lived here have been moved to:

    test_subnet_write.py   — Subnet creation, mutation, expression builder
    test_pool_write.py     — Pool creation, mutation, frozen-field checks
    test_address_write.py  — IpAddress creation, mutation, frozen-field checks
    test_errors.py         — Invalid-input / constraint-violation error cases
    test_delete.py         — Valid and invalid delete operations

Session-scoped fixtures (block, child_subnet, terminal_subnet, pool, addr1,
grandchild_subnet) now live in conftest.py so all files share them.
"""

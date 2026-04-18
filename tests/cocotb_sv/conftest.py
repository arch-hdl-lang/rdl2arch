"""Prevent pytest from treating cocotb test modules as pytest tests.

These modules use `@cocotb.test()` and are invoked by the Verilator runner via
`test_verilator.py`. They are not self-contained pytest test functions and
must not be imported into the pytest collection.
"""

collect_ignore_glob = ["cocotb_tests/test_*.py"]

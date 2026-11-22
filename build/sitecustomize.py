import os
import unittest  # noqa: F401  before sqlglot in every process, as under pytest

if "FACTS" in os.environ:
    __import__("process_facts").begin()
    __import__("gap_facts").begin()

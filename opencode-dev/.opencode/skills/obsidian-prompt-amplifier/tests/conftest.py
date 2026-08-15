# -*- coding: utf-8 -*-
"""共享 conftest: 将 tools 目录加入 path。"""
import os
import sys

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

"""
构建期（PyInstaller）强制收集剪映导入依赖。

背景：
- 我们在打包时把 `scripts/` 作为 data 文件塞进 exe（_internal/jy_skill/scripts）。
- 运行时会动态 `import jy_wrapper` 来“保存到剪映草稿”。
- 但 PyInstaller 不会分析 data 文件里的 Python 依赖，因此会出现缺模块（例如 uuid）的问题。

本模块的目的：
- 在“构建期”让 PyInstaller 看到 `jy_wrapper` 及其依赖树（utils/core/vendor/pyJianYingDraft 等），
  从而把这些 Python 模块打进包里，避免运行时 ImportError。

运行时：
- 本模块即使导入失败也不影响录屏功能（会被忽略）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _inject_repo_scripts_path() -> None:
    """把仓库 scripts/vendor 路径注入 sys.path（仅用于构建期分析）。"""
    base = Path(__file__).resolve().parent
    repo_root = base.parent
    scripts_dir = repo_root / "scripts"
    vendor_dir = scripts_dir / "vendor"

    # 构建期：这两个路径是存在的；运行时 exe 内则未必存在，但失败也没关系
    if scripts_dir.exists():
        p = str(scripts_dir.resolve())
        if p not in sys.path:
            sys.path.insert(0, p)
    if vendor_dir.exists():
        p = str(vendor_dir.resolve())
        if p not in sys.path:
            sys.path.insert(0, p)


def force_collect() -> None:
    """
    尽可能导入剪映相关模块，让 PyInstaller 收集依赖。

    注意：
    - 不在这里做任何“运行时副作用”（不创建草稿、不调用剪映）。
    - 仅用于让 PyInstaller 收集模块依赖图。
    """

    _inject_repo_scripts_path()

    # 常见标准库（确保被收集；也能帮助发现环境异常）
    import uuid  # noqa: F401
    import json  # noqa: F401
    import argparse  # noqa: F401
    import difflib  # noqa: F401
    import asyncio  # noqa: F401

    # 剪映导入链路核心模块：
    # 注意：不要在此处使用 “import utils/core” 这种宽泛名称，
    # 否则在复杂 Python 环境里可能命中同名第三方包，导致 PyInstaller 扫入大量无关依赖。
    import jy_wrapper  # noqa: F401
    import smart_zoomer  # noqa: F401
    import pyJianYingDraft  # noqa: F401


try:
    # 构建期导入一次即可；运行时失败也没关系
    if os.environ.get("JY_FORCE_COLLECT", "1") == "1":
        force_collect()
except Exception:
    pass


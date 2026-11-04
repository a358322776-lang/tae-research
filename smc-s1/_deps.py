"""依赖加载：复用 research-lab 的验证器与统一成本函数。

smc-s1 不复制 Bar 契约与成本公式；validator.Bar 与 cost_model
以文件路径加载（research-lab 目录名含连字符，不可作包名导入）。
加载失败即报错，不降级为本地复刻。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_RESEARCH_LAB = _REPO_ROOT / "research-lab"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    # dataclass 处理须经 sys.modules 取到模块命名空间，先注册再执行。
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_validator = _load_module("smc_validator", _RESEARCH_LAB / "validator.py")
_cost_model = _load_module("smc_cost_model", _RESEARCH_LAB / "cost_model.py")

Bar = _validator.Bar
ContractError = _validator.ContractError
check_bars = _validator.check_bars
cost_model = _cost_model

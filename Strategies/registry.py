"""策略注册表。

功能：按名称查找策略类，支持 cli.py 按名称选择策略。
设计：策略在包内通过 register 注册，cli 通过 get_strategy 查找。
依赖：Strategies.base.CStrategy。
"""
from typing import Dict, Type

from .base import CStrategy


# 策略注册表：名称 -> 策略类
_REGISTRY: Dict[str, Type[CStrategy]] = {}


def register(name: str):
    """策略类装饰器：注册到全局注册表。
    功能：声明策略名称，供 cli 按名称查找
    输入：name - 策略名称（如 'example_ma'、'chan'）
    输出：装饰器
    """
    def decorator(cls: Type[CStrategy]) -> Type[CStrategy]:
        if not issubclass(cls, CStrategy):
            raise TypeError(f"{cls} 必须是 CStrategy 的子类")
        _REGISTRY[name] = cls
        return cls
    return decorator


def get_strategy(name: str) -> Type[CStrategy]:
    """按名称查找策略类。
    功能：从注册表获取策略类
    输入：name - 策略名称
    输出：策略类
    异常：未注册则抛 KeyError
    """
    if name not in _REGISTRY:
        # 触发各策略包的注册（导入即注册）
        _auto_discover()
    if name not in _REGISTRY:
        raise KeyError(f"未注册的策略: {name}，已注册: {list(_REGISTRY.keys())}")
    return _REGISTRY[name]


def list_strategies() -> Dict[str, Type[CStrategy]]:
    """列出所有已注册策略。
    功能：触发自动发现后返回完整注册表
    输出：{name: 策略类}
    """
    _auto_discover()
    return dict(_REGISTRY)


def _auto_discover() -> None:
    """自动发现并导入策略模块，触发注册。
    功能：导入已知策略模块，使其执行 @register
    设计：显式列出策略模块名，避免动态扫描的副作用
    """
    import importlib
    for mod in ["Strategies.example_ma.ma_strategy", "Strategies.chan.chan_strategy"]:
        try:
            importlib.import_module(mod)
        except ImportError:
            # 可选依赖缺失（如缠论需 CKLine_Unit）时跳过，不影响其他策略
            pass

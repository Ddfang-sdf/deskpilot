"""执行层（详细设计 §9）。

只执行、不判断。Executor 真实实现见 executor.core；
DesktopProbe 提供窗口探测（binding.WindowProbe 的实现）。
"""

from .core import Executor
from .probe import DesktopProbe

__all__ = ["Executor", "DesktopProbe"]

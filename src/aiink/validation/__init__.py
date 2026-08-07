"""一致性校验（§8）：L1 确定性 + 大纲偏差；L2 阶段 3 接入。"""

from aiink.validation.l1 import L1Validator
from aiink.validation.service import ValidationService, outline_deviation

__all__ = ["L1Validator", "ValidationService", "outline_deviation"]

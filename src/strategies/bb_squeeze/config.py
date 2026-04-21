from dataclasses import dataclass

@dataclass
class BBSqueezeConfig:
    bb_period: int
    bb_dev: float
    bw_ma_period: int
    atr_period: int
    constant: float
    adaptive_constant: float
    max_spread: float
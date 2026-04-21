import math
from collections import deque
from typing import Tuple, Optional

"""
Incremental volatility indicators for live trading.

Maintains state to avoid recalculating entire history on every tick.
Only updates on new candle closes.
"""


class IncrementalVolatility:

     # Updates only when new candle data arrives, caches results between ticks.
    
    def __init__(self, bb_period: int = 25, bb_dev: float = 1.0, atr_period: int = 20):
        self.bb_period = bb_period
        self.bb_dev = bb_dev
        self.atr_period = atr_period
        
        # Rolling windows
        self.closes = deque(maxlen=bb_period)
        self.tr_values = deque(maxlen=atr_period)

        # Running sums for BB
        self._sum = 0.0
        self._sum_sq = 0.0

        # Running sum for ATR
        self._tr_sum = 0.0
        
        # Cached results
        self._bb_upper: Optional[float] = None
        self._bb_lower: Optional[float] = None
        self._bb_middle: Optional[float] = None
        self._atr: float = 0.0
        
    def update(
        self,
        close: float,
        high: float,
        low: float,
        prev_close: Optional[float] = None
    ) -> None:
        """
        Update with new tick data.
            prev_close (required for True Range calculation on first update)
        """
        # ===== BOLLINGER UPDATE =====
        if len(self.closes) == self.bb_period:
            old = self.closes.popleft()
            self._sum -= old
            self._sum_sq -= old * old

        self.closes.append(close)
        self._sum += close
        self._sum_sq += close * close

        # ===== TRUE RANGE UPDATE =====
        if prev_close is not None:
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )

            if len(self.tr_values) == self.atr_period:
                old_tr = self.tr_values.popleft()
                self._tr_sum -= old_tr

            self.tr_values.append(tr)
            self._tr_sum += tr
        
        # ===== RECALCULATE (O(1)) =====
        self._recalculate()
    
    def _recalculate(self) -> None:
        """Recalculate BB and ATR using running sums."""

        # ---- Bollinger Bands ----
        n = len(self.closes)
        if n < self.bb_period:
            self._bb_upper = None
            self._bb_lower = None
            self._bb_middle = None
        else:
            mean = self._sum / n
            variance = (self._sum_sq / n) - (mean * mean)
            variance = max(variance, 0.0)  # prevent negative due to floating point
            std = math.sqrt(variance)
            
            self._bb_middle = mean
            self._bb_upper = mean + self.bb_dev * std
            self._bb_lower = mean - self.bb_dev * std
        
        # ---- ATR ----
        m = len(self.tr_values)
        if m > 0:
            self._atr = self._tr_sum / m
        else:
            self._atr = 0.0
    
     # ===== GETTERS =====

    def get_bollinger_bands(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        return self._bb_upper, self._bb_lower, self._bb_middle

    def get_atr(self) -> float:
        return self._atr

    def get_bandwidth(self) -> float:
        if (
            self._bb_middle is None
            or self._bb_upper is None
            or self._bb_lower is None
            or self._bb_middle == 0
        ):
            return 0.0
        return (self._bb_upper - self._bb_lower) / self._bb_middle

    def is_ready(self) -> bool:
        return len(self.closes) >= self.bb_period and len(self.tr_values) > 0

class BandwidthMACalculator:
    def __init__(self, bw_ma_period: int = 150):
        self.bw_ma_period = bw_ma_period
        self.values = deque(maxlen=bw_ma_period)
        self._sum = 0.0

    def update(self, value: float) -> None:
        if len(self.values) == self.bw_ma_period:
            old = self.values.popleft()
            self._sum -= old

        self.values.append(value)
        self._sum += value

    def get_bandwidth_ma(self) -> float:
        if len(self.values) == 0:
            return 0.0
        return self._sum / len(self.values)

    def is_ready(self) -> bool:
        return len(self.values) >= self.bw_ma_period
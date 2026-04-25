'''src/strategies/bb_squeeze/signal.py'''
from typing import Optional

from src.core.types import Signal, Direction, MarketState
from src.strategies.bb_squeeze.config import BBSqueezeConfig
from src.strategies.base import Strategy
from src.indicators.incremental.volatility_live import (
    IncrementalVolatility,
    BandwidthMACalculator
)
from src.utils.logger import log

class BBSqueeze(Strategy):
    def __init__(self,config: BBSqueezeConfig):
        super().__init__(config)

        # adaptive state
        self._last_trade_was_loss = False

        self._last_exit_bar_time = None # Data of exit time and holding period

        self._current_bar_time = None
        
        self._last_signal_setup_time = None # State of used candle

        self.indicators = IncrementalVolatility(
            bb_period=config.bb_period,
            bb_dev=config.bb_dev,
            atr_period=config.atr_period,
        )

        self.bandwidth_ma = BandwidthMACalculator(
            bw_ma_period=config.bw_ma_period
        )

    def on_new_bar(self, history: dict):  
        closes = history["close"]
        highs = history["high"]
        lows = history["low"]

        if len(closes) < 2:
            return

        close = closes[-2]
        high = highs[-2]
        low = lows[-2]

        self.indicators.update(close, high, low)

        # update bandwidth MA
        bw = self.indicators.get_bandwidth()
        self.bandwidth_ma.update(bw)


    # -----------------------------
    # Entry logic
    # -----------------------------
    def generate_signal(
        self,
        market_state: MarketState,
        history: dict,
        spread: float,
    ) -> Optional[Signal]:

        current_bar_time = history["timestamp"][-1]
        setup_bar_time = history["timestamp"][-2]

        if self._current_bar_time != current_bar_time:
            log(
                f"[BAR DETECTED] ts={current_bar_time}, prev={self._current_bar_time}",
                level="INFO"
            ) 
            self.on_new_bar(history)
            self._current_bar_time = current_bar_time 
        
        if not (self.indicators.is_ready() and self.bandwidth_ma.is_ready()):
            log(f"[FILTERED] indicators: {self.indicators.is_ready()}, bw_ma: {self.bandwidth_ma.is_ready()}")
            return None 

        if self._last_exit_bar_time == self._current_bar_time:
            log("[FILTERED] same bar re-entry")
            return None
        
        if setup_bar_time == self._last_signal_setup_time:
            log("[FILTERED] this setup candle was already used")
            return None

        if spread > self.config.max_spread:
            log(f"[FILTERED] spread too high: {spread}")
            return None
        
        closes = history["close"]
        highs = history["high"]
        lows = history["low"]
        opens = history["open"]

        # previous candle
        open2 = opens[-2]
        close2 = closes[-2]
        high2 = highs[-2]
        low2 = lows[-2]

        high1 = highs[-1]
        low1 = lows[1]

    # ===== USE INCREMENTAL VALUES =====
        prev_upper, prev_lower, _ = self.indicators.get_bollinger_bands()

        # early BB = None prevention
        if prev_upper is None or prev_lower is None:
            return None
        
        atr_value = self.indicators.get_atr()

        # early ATR = 0 prevention
        if atr_value == 0:
            return None
        
        bw = self.indicators.get_bandwidth()
        bw_ma = self.bandwidth_ma.get_bandwidth_ma()

        if bw_ma == 0:
            return None

        # bandwidth filter
        if bw >= self.config.constant * bw_ma:
            return None

        # adaptive filter
        if self._last_trade_was_loss:
            if abs(close2 - open2) <= self.config.adaptive_constant * atr_value:
                return None

        # invalid candle
        valid_candle = not (
            (open2 > prev_upper and close2 < prev_upper)
            or (open2 < prev_lower and close2 > prev_lower)
        )

        # -----------------------------
        # BUY
        # -----------------------------
        if  high2 >= prev_upper and close2 > prev_upper and valid_candle:
            if market_state.ask and high1 > high2 + 0.1 * atr_value:
                self._last_signal_setup_time = setup_bar_time  # consume setup candle
                return Signal(
                    signal_id=f"{market_state.timestamp}_BUY",
                    symbol=market_state.symbol,
                    timestamp=market_state.timestamp,
                    direction=Direction.LONG,
                    strategy_id=self.strategy_id,
                    entry_price=market_state.ask,
                    notes="BB squeeze breakout BUY",
                )

        # -----------------------------
        # SELL
        # -----------------------------
        if low2 <= prev_lower and close2 < prev_lower and valid_candle:
            if market_state.bid and low1 < low2 - 0.1 * atr_value:
                self._last_signal_setup_time = setup_bar_time  # consume setup candle
                return Signal(
                    signal_id=f"{market_state.timestamp}_SELL",
                    symbol=market_state.symbol,
                    timestamp=market_state.timestamp,
                    direction=Direction.SHORT,
                    strategy_id=self.strategy_id,
                    entry_price=market_state.bid,
                    notes="BB squeeze breakout SELL",
                )

        return None

    # -----------------------------
    # Exit logic (returns True/False)
    # -----------------------------
    def check_exit(self, trade, market_state, closes) -> bool:
        upper, lower, middle = self.indicators.get_bollinger_bands()
        # not ready → no exit
        if upper is None or lower is None:
            return False

        if trade.direction == Direction.LONG:
            # exit if price returns inside / below lower band
            if market_state.bid and closes[-1] <= lower:
                return True

        elif trade.direction == Direction.SHORT:
            # exit if price returns inside / above upper band
            if market_state.ask and closes[-1] >= upper:
                return True

        return False

    # -----------------------------
    # Update state
    # -----------------------------
    def update_trade_result(self, trade):
        self._last_exit_bar_time = self._current_bar_time

        if trade.net_pnl is None:
            return

        self._last_trade_was_loss = trade.net_pnl < 0
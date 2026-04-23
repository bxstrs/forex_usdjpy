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

class BBSqueezeStrategy(Strategy):
    def __init__(self,config: BBSqueezeConfig):
        super().__init__(config)
        self.strategy_id = self.__class__.__name__

        # adaptive state
        self.last_trade_was_loss = False
        self._near_breakout_logged = False
        self.last_close_time = None
        self.last_close_bar_time = None

        self.vol = IncrementalVolatility(
            bb_period=config.bb_period,
            bb_dev=config.bb_dev,
            atr_period=config.atr_period,
        )

        self.bw_ma = BandwidthMACalculator(
            bw_ma_period=config.bw_ma_period
        )

        self._last_bar_time = None

    def on_new_bar(self, history: dict):
        closes = history["close"]
        highs = history["high"]
        lows = history["low"]

        if len(closes) < 2:
            return

        close = closes[-1]
        high = highs[-1]
        low = lows[-1]
        prev_close = closes[-2]

        self.vol.update(close, high, low, prev_close)

        # update bandwidth MA
        bw = self.vol.get_bandwidth()
        self.bw_ma.update(bw)


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

        if self._last_bar_time != current_bar_time:
            log(
                f"[BAR DETECTED] ts={current_bar_time}, prev={self._last_bar_time}",
                level="INFO"
            )
            self.on_new_bar(history)
            self._last_bar_time = current_bar_time
        
        # readiness check
        if not (self.vol.is_ready() and self.bw_ma.is_ready()):
            return None

        # prevent same bar re-entry
        if self.last_close_bar_time == self._last_bar_time:
            return None

        if spread > self.config.max_spread:
            return None
        
        closes = history["close"]
        highs = history["high"]
        lows = history["low"]
        opens = history["open"]

        # previous candle
        open1 = opens[-1]
        close1 = closes[-1]
        high1 = highs[-1]
        low1 = lows[-1]

    # ===== USE INCREMENTAL VALUES =====
        upper, lower, middle = self.vol.get_bollinger_bands()

        # early BB = None prevention
        if upper is None or lower is None:
            return None
        
        atr_value = self.vol.get_atr()

        # early ATR = 0 prevention
        if atr_value == 0:
            return None
        
        bw = self.vol.get_bandwidth()
        bw_ma = self.bw_ma.get_bandwidth_ma()

        if close1 > upper * 0.98 or close1 < lower * 0.98:
            if not self._near_breakout_logged:
                log(
                    f"[NEAR BREAKOUT] close={close1:.5f}, upper={upper}, lower={lower}, "
                    f"bw={bw:.6f}, bw_ma={bw_ma:.6f}", level="INFO"
                )
                self._near_breakout_logged = True
        else:
            self._near_breakout_logged = False

        if bw_ma == 0:
            return None

        # bandwidth filter
        if bw >= self.config.constant * bw_ma:
            return None

        # adaptive filter
        if self.last_trade_was_loss:
            if abs(close1 - open1) <= self.config.adaptive_constant * atr_value:
                return None

        # invalid candle
        valid_candle = not (
            (open1 > upper and close1 < lower)
            or (open1 < lower and close1 > upper)
        )

        # -----------------------------
        # BUY
        # -----------------------------
        if close1 > upper and valid_candle:
            if market_state.ask and market_state.ask > high1 + 0.1 * atr_value:
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
        if close1 < lower and valid_candle:
            if market_state.bid and market_state.bid < low1 - 0.1 * atr_value:
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
    def check_exit(self, trade, market_state, history) -> bool:
        upper, lower, middle = self.vol.get_bollinger_bands()
        # not ready → no exit
        if upper is None or lower is None:
            return False

        if trade.direction == Direction.LONG:
            # exit if price returns inside / below lower band
            if market_state.bid and market_state.bid <= lower:
                return True

        elif trade.direction == Direction.SHORT:
            # exit if price returns inside / above upper band
            if market_state.ask and market_state.ask >= upper:
                return True

        return False

    # -----------------------------
    # Update state
    # -----------------------------
    def update_trade_result(self, trade):
        self.last_close_time = trade.exit_time
        self.last_close_bar_time = self._last_bar_time

        if trade.net_pnl is None:
            return

        self.last_trade_was_loss = trade.net_pnl < 0
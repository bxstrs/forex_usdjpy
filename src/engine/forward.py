'''src/engine/forward.py'''
import time
import MetaTrader5 as mt5

from src.core.types import MarketState
from src.strategies.strategy_loader import load_strategy
from src.execution.mt5_bridge import MT5Bridge
from src.utils.logger import log
from src.utils.data_logger import DataLogger
from src.execution.position_manager import PositionManager

# ============================================================================
# Configuration
# ============================================================================

SYMBOL = "ETHUSD#"
TIMEFRAME = mt5.TIMEFRAME_H4
STR_TIMEFRAME = "4h"

TICK_SLEEP = 0.1  # seconds (100ms = ~10 ticks/sec)
RATE_FETCH_INTERVAL = 1  # fetch full history every N ticks (reduce redundant calls)

# ============================================================================
# Helpers
# ============================================================================

datalogger = DataLogger()

def fetch_data(bridge):
    history = bridge.get_rates(SYMBOL, TIMEFRAME, 220)
    tick = bridge.get_tick(SYMBOL)

    if history is None or tick is None:
        return None, None

    return history, tick


def build_market_state(history, tick, use_previous=False):
    idx = -2 if use_previous else -1

    return MarketState(
        symbol=SYMBOL,
        interval=STR_TIMEFRAME,
        timestamp=history["timestamp"][idx],
        open=history["open"][idx],
        high=history["high"][idx],
        low=history["low"][idx],
        close=history["close"][idx],
        bid=tick.bid,
        ask=tick.ask
    )

def warmup_strategy(strategy, history):
    closes = history["close"]
    highs = history["high"]
    lows = history["low"]

    for i in range(1, len(closes)):
        sub_history = {
            "close": closes[:i+1],
            "high": highs[:i+1],
            "low": lows[:i+1],
            "open": history["open"][:i+1],
            "timestamp": history["timestamp"][:i+1],
        }
        strategy.on_new_bar(sub_history)
    strategy._current_bar_time = history["timestamp"][-1]
    log("warmup call succeeded, indicators ready")

# =========================
# Entry Logic
# =========================
def try_entry(
    bridge,
    position_manager,
    strategy,
    market_state,
    history,
    spread,
    current_bar_time,
    _last_entry_bar_time
):
    # prevent risk rule breach
    if not position_manager.can_trade():
        return False, _last_entry_bar_time

    # enforce position rule
    if position_manager.has_open_position(SYMBOL, strategy.strategy_id):
        return False, _last_entry_bar_time

    # prevent same bar entry
    if _last_entry_bar_time == current_bar_time:
        return False, _last_entry_bar_time

    signal = strategy.generate_signal(
        market_state=market_state,
        history=history,
        spread=spread
    )

    if not signal:
        return False, _last_entry_bar_time

    direction = "BUY" if signal.direction.name == "LONG" else "SELL"

    log(f"[ENTRY] {signal.direction} at expected price: {signal.entry_price}", level="SIGNAL")

    result = bridge.send_order(
        symbol=SYMBOL,
        direction=direction,
        volume=0.1,
        magic=strategy.magic_number,
        comment=strategy.strategy_id
    )

    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        datalogger.log_trade(
            ts=time.time(),
            type="ENTRY",
            direction=direction,
            price=signal.entry_price,
            pnl=0,
            note="entry"
        )
        return True, current_bar_time

    return False, _last_entry_bar_time


# =========================
# MAIN LOOP
# =========================
def main():
    
    bridge = MT5Bridge()
    if not bridge.connect():
        log("MT5 connection failed")
        return

    strategy = load_strategy("bb_squeeze")
    position_manager = PositionManager(bridge)

    log(f"Loaded strategy: {strategy.strategy_id}")

    history, tick = fetch_data(bridge)
    if history is None:
        log("Initial data fetch failed")
        return

    warmup_strategy(strategy, history)
    
    #Loop state
    tick_counter = 0
    _last_entry_bar_time = None
    current_bar_time = history["timestamp"][-1]
    last_fetch_time = time.time()
    loop_start = time.time()

    _had_position = position_manager.has_open_position(SYMBOL, strategy.strategy_id)

    try:
        while True:
            tick_counter += 1
            loop_iteration_start = time.time()

            # refresh history periodically
            if time.time() - last_fetch_time > RATE_FETCH_INTERVAL:
                history, tick = fetch_data(bridge)

                if history is None or tick is None:
                    log("Failed to fetch market data, retrying...")
                    time.sleep(TICK_SLEEP)
                    continue

                current_bar_time = history["timestamp"][-1]
                last_fetch_time = time.time()

                if tick_counter % 100 == 0:
                    log(f"[TICK {tick_counter}] Bar time: {current_bar_time}, "
                        f"Bid: {tick.bid:.5f}, Ask: {tick.ask:.5f}",
                        level="INFO") # Bid, Ask will be fetched from tick data.
            else:
                tick = bridge.get_tick(SYMBOL)
                if tick is None:
                    log(f"[TICK {tick_counter}] Failed to fetch tick data", level="ERROR")
                    time.sleep(TICK_SLEEP)
                    continue
                if tick_counter % 100 == 0:
                    log(f"[TICK {tick_counter}] Bid: {tick.bid:.5f}, Ask: {tick.ask:.5f}", level="INFO")

            # =========================
            # GLOBAL DATA GUARD (REQUIRED)
            # =========================
            if history is None:
                log("[DATA ERROR] history is None, skipping iteration", level="ERROR")
                time.sleep(TICK_SLEEP)
                continue

            # =========================
            # EXIT (current candle)
            # =========================
            current_state = build_market_state(history, tick, use_previous=False)
            position_manager.handle_exit(strategy, current_state, history)
            
            current_has_position = position_manager.has_open_position(SYMBOL, strategy.strategy_id)
 
            if _had_position and not current_has_position:
                log(
                    "[POSITION CLOSED] Blocking re-entry for current bar.",
                    level="INFO",
                )
                _last_entry_bar_time = current_bar_time
 
            _had_position = current_has_position

            # =========================
            # ENTRY (previous candle)
            # =========================
            setup_state = build_market_state(history, tick, True)
            spread = bridge.get_spread(SYMBOL)

            execute, _last_entry_bar_time = try_entry(
                bridge,
                position_manager,
                strategy,
                setup_state,
                history,
                spread,
                current_bar_time,
                _last_entry_bar_time
            )

            if execute:
                _had_position = True
                loop_time = time.time() - loop_iteration_start
                log(f"Signal executed in {loop_time:.3f}s")

            time.sleep(TICK_SLEEP)

    except KeyboardInterrupt:
        log("Stopped by user")
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        bridge.shutdown()
        elapsed = time.time() - loop_start
        log(f"Stopped. Processed {tick_counter} ticks in {elapsed:.1f}s ({tick_counter/elapsed:.1f} ticks/sec)")


def run_forward(strategy_name: str = "bb_squeeze") -> None:
    main()
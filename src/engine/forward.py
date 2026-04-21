import time
import MetaTrader5 as mt5
from src.core.types import MarketState
from src.strategies.strategy_loader import load_strategy
from src.execution.mt5_bridge import MT5Bridge
from src.execution.converter import convert_position_to_trade
from src.utils.logger import log

# ============================================================================
# Configuration
# ============================================================================

symbol = "ETHUSD#"
timeframe = mt5.TIMEFRAME_M1
str_timeframe = "1m"

# Performance tuning
TICK_SLEEP = 0.1  # seconds (100ms = ~10 ticks/sec)
RATE_FETCH_INTERVAL = 1  # fetch full history every N ticks (reduce redundant calls)

# State
last_entry_bar_time = None
tick_counter = 0

def fetch_and_prepare_data(bridge):

    # Fetch market data and prepare for analysis.
    history = bridge.get_rates(symbol, timeframe, 180)
    tick = bridge.get_tick(symbol)
    
    if history is None or tick is None:
        return None, None, None
    
    return history, tick, history["close"]


def has_open_position(bridge, strategy):
    # Check an open position for this strategy/symbol.
    positions = bridge.get_positions(symbol)
    return len(positions) > 0 if positions else False


def execute_exit_logic(bridge, strategy, market_state, closes):
    
    #Exit any open positions per conditions and current CANDLE
    positions = bridge.get_positions(symbol)
    
    if not positions:
        return
    
    for pos in positions:
        trade = convert_position_to_trade(pos)
        
        # Check if we should exit
        if strategy.check_exit(trade, market_state, closes):
            log(f"[EXIT SIGNAL] {trade.direction} at {market_state.bid if trade.direction.name == 'LONG' else market_state.ask}", level="SIGNAL")
            bridge.close_position(pos)
            
            # Update strategy state with trade result
            trade.exit_price = pos.price_current
            trade.exit_time = market_state.timestamp
            trade.net_pnl = pos.profit
            strategy.update_trade_result(trade)


def execute_entry_logic(bridge, strategy, market_state, history, spread, current_bar_time):
    """
    Checks PREVIOUS/CLOSED candle (shift=1) for conditions.
    Executes at CURRENT tick prices.
    """
    global last_entry_bar_time
    
    # Prevent re-entry on same closed candle
    # (last_close_time from strategy tracks when we last exited)
    if last_entry_bar_time == current_bar_time:
        return False
    
    # Prevent duplicate positions
    if has_open_position(bridge, strategy):
        return False
    
    # Generate signal (checks closed candle conditions)
    signal = strategy.generate_signal(
        market_state=market_state,
        history=history,
        spread=spread
    )
    
    if not signal:
        return False
    
    current_price = market_state.bid if signal.direction.name == "LONG" else market_state.ask
    
    if signal.direction.name == "LONG" and current_price <= signal.entry_price:
        return False
    if signal.direction.name == "SHORT" and current_price >= signal.entry_price:
        return False
    
    # Execute order at current market prices
    direction = "BUY" if signal.direction.name == "LONG" else "SELL"
    log(f"[ENTRY SIGNAL] {signal.direction} at {signal.entry_price}: {signal.notes}", level="SIGNAL")
    
    result = bridge.send_order(symbol, direction, volume=0.1)
    
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        last_entry_bar_time = current_bar_time
        return True
    
    return False


def build_market_state(history, tick, use_previous=False):
    #Build MarketState from history and tick data.
    idx = -2 if use_previous else -1
    
    return MarketState(
        symbol=symbol,
        interval=str_timeframe,
        timestamp=history["timestamp"][idx],
        open=history["open"][idx],
        high=history["high"][idx],
        low=history["low"][idx],
        close=history["close"][idx],
        bid=tick.bid,
        ask=tick.ask
    )


# ============================================================================
# Main Loop
# ============================================================================

def main():
    """Main forward testing loop."""
    global tick_counter, last_entry_bar_time
    
    # Initialize
    bridge = MT5Bridge()
    if not bridge.connect():
        log("Failed to connect to MT5")
        return
    
    strategy = load_strategy("bb_squeeze")
    log(f"Loaded strategy: {strategy.strategy_id}")
    
    last_rate_fetch_time = time.time()
    loop_start = time.time()

    # =========================
    # INITIALIZE BEFORE LOOP
    # =========================
    history, tick, closes = fetch_and_prepare_data(bridge)

    if history is None:
        log("Failed initial data fetch")
        return

    current_bar_time = history["timestamp"][-1]
    # =========================
    
    try:
        while True:
            tick_counter += 1
            loop_iteration_start = time.time()
            
            # Periodically refresh full history (reduce API calls)
            if time.time() - last_rate_fetch_time > RATE_FETCH_INTERVAL:
                history, tick, closes = fetch_and_prepare_data(bridge)
                
                if history is None:
                    log("Failed to fetch market data, retrying...")
                    time.sleep(TICK_SLEEP)
                    continue
                
                last_rate_fetch_time = time.time()
                current_bar_time = history["timestamp"][-1]
                
                if tick_counter % 100 == 0:
                    log(f"[TICK {tick_counter}] Bar time: {current_bar_time}, "
                        f"Bid: {tick.bid:.5f}, Ask: {tick.ask:.5f}",
                        level="INFO") # Bid, Ask will be fetched from tick data.
            else:
                # Quick tick fetch (just prices, not full history)
                tick = bridge.get_tick(symbol)
                if tick is None:
                    log(f"[TICK {tick_counter}] Failed to fetch tick data", level="ERROR")
                    time.sleep(TICK_SLEEP)
                    continue
                if tick_counter % 100 == 0:
                    log(f"[TICK {tick_counter}] Bid: {tick.bid:.5f}, Ask: {tick.ask:.5f}", level="INFO")
            
            # Exit logic (check current candle)
            current_market_state = build_market_state(history, tick, use_previous=False)
            execute_exit_logic(bridge, strategy, current_market_state, closes)
            
            # Entry logic (check previous/closed candle)
            previous_market_state = build_market_state(history, tick, use_previous=True)
            spread = bridge.get_spread(symbol)
            
            signal_executed = execute_entry_logic(
                bridge,
                strategy,
                previous_market_state,
                history,
                spread,
                current_bar_time
            )
            
            loop_time = time.time() - loop_iteration_start
            
            if signal_executed:
                log(f"Signal executed in {loop_time:.3f}s")
            
            # Sleep to avoid hammering the API
            time.sleep(TICK_SLEEP)
    
    except KeyboardInterrupt:
        log("Shutdown requested")
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        bridge.shutdown()
        elapsed = time.time() - loop_start
        log(f"Stopped. Processed {tick_counter} ticks in {elapsed:.1f}s ({tick_counter/elapsed:.1f} ticks/sec)")

def run_forward(strategy_name: str = "bb_squeeze"):
    main()
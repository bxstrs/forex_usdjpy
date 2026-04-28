'''src/execution/position_manager.py'''
from typing import List, Tuple

import MetaTrader5 as mt5  
from src.execution.converter import convert_position_to_trade   
from src.core.types import Trade
from src.utils.logger import log
from src.utils.data_logger import DataLogger

MAX_CONSECUTIVE_LOSSES = 5
MAX_DRAWDOWN = 0.2  # 20% drawdown

datalogger = DataLogger()

class PositionManager:
    def __init__(self, bridge):
        self.bridge = bridge

        # Risk tracking state
        self._consecutive_losses: int = 0
        self._peak_balance: float = 0.0
        self._trading_halted: bool = False

    # ------------------------------------------------------------------
    # Position Queries
    # ------------------------------------------------------------------

    def get_strategy_positions(self, symbol: str, strategy_id: str) -> List[Tuple]:
        positions = self.bridge.get_positions(symbol)
        if not positions:
            return []

        result = []
        for pos in positions:
            match = pos.comment == str(strategy_id)
            log(
                f"[POSITION] ticket={pos.ticket} | "
                f"raw_comment='{pos.comment}' | "
                f"expected='{strategy_id}' | "
                f"exact_match={match} | "
                f"startswith={pos.comment.startswith(strategy_id)}",
                level="DEBUG"
            )
            if match:
                result.append((pos, convert_position_to_trade(pos)))

        log(f"[POSITION] {len(result)} position(s) matched strategy_id='{strategy_id}'", level="DEBUG")
        return result

    def has_open_position(self, symbol: str, strategy_id: str) -> bool:
        return len(self.get_strategy_positions(symbol, strategy_id)) > 0
    
    # ------------------------------------------------------------------
    # Risk Guards
    # ------------------------------------------------------------------
 
    def can_trade(self) -> bool:
        """triggered if risk limits have been breached."""
        if self._trading_halted:
            log(
                "[RISK] Trading halted — risk limit reached. Restart to resume.",
                level="WARNING",
            )
        return not self._trading_halted
    
    def _update_risk(self, trade: Trade) -> None:
        """Update risk state after a trade closes."""
        pnl = trade.net_pnl or 0.0
 
        if pnl < 0:
            self._consecutive_losses += 1
            log(
                f"[RISK] Consecutive losses: {self._consecutive_losses}/{MAX_CONSECUTIVE_LOSSES}",
                level="WARNING",
            )
            if self._consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                self._trading_halted = True
                log(
                    f"[RISK] Max consecutive losses ({MAX_CONSECUTIVE_LOSSES}) reached. "
                    "Halting trading.",
                    level="WARNING",
                )
        else:
            self._consecutive_losses = 0 # reset on win
 
    # ------------------------------------------------------------------
    # Exit Handler
    # ------------------------------------------------------------------

    def handle_exit(self, strategy, market_state, history) -> None:
        trades = self.get_strategy_positions(
            market_state.symbol,
            strategy.strategy_id
        )

        for pos, trade in trades:
            if strategy.check_exit(trade, market_state, history["close"]):
                exit_price = (
                    market_state.bid
                )
                log(f"[EXIT SIGNAL] {trade.direction} at {exit_price}", level="SIGNAL")

                result = self.bridge.close_position(pos)
                actual_exit_price = result.price if result and result.retcode == mt5.TRADE_RETCODE_DONE else market_state.bid

                deal_ticket = result.deal
                deals = self.bridge.history_deals_get(ticket=deal_ticket)
                actual_pnl = deals[0].profit if deals else None

                datalogger.log_trade(
                    ts=market_state.timestamp,
                    type="EXIT",
                    direction=trade.direction.name,
                    price=exit_price,
                    pnl=trade.net_pnl,
                    note="exit_signal"
                )

                trade.exit_price = actual_exit_price
                trade.exit_time = market_state.timestamp
                trade.net_pnl = actual_pnl

                self._update_risk(trade)
                strategy.update_trade_result(trade)
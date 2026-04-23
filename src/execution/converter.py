'''src/execution/converter.py'''
import MetaTrader5 as mt5
from src.core.types import Trade, Direction
from datetime import datetime, timezone


def convert_position_to_trade(pos) -> Trade:
    direction = (
        Direction.LONG
        if pos.type == mt5.POSITION_TYPE_BUY
        else Direction.SHORT
    )

    return Trade(
        trade_id=str(pos.ticket),
        strategy_id=pos.comment,
        symbol=pos.symbol,
        direction=direction,
        entry_price=pos.price_open,
        exit_price=None,
        volume=pos.volume,
        entry_time=datetime.fromtimestamp(pos.time, tz=timezone.utc),
        exit_time=None,
        net_pnl=pos.profit
    )
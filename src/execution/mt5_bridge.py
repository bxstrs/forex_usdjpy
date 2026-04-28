'''src/execution/mt5_bridge.py'''
import os
import MetaTrader5 as mt5
from typing import Dict, Optional
from dotenv import load_dotenv
    # -----------------------------
    # Implemented as MT5 documentation suggested, Error warnings is not related
    # -----------------------------

load_dotenv()

class MT5Bridge:
    def __init__(self, login=None, password=None, server=None):
        self.connected = False

        self.login = login or int(os.getenv("MT5_LOGIN", 0))
        self.password = password or os.getenv("MT5_PASSWORD")
        self.server = server or os.getenv("MT5_SERVER")

    # -----------------------------
    # Connection
    # -----------------------------
    def connect(self) -> bool:
        if self.login:
            self.connected = mt5.initialize(
                login=self.login,
                password=self.password,
                server=self.server
            )
        else:
            self.connected = mt5.initialize()

        if not self.connected:
            error = mt5.last_error()
            raise RuntimeError(f"MT5 init failed: {error}")
        return self.connected

    def shutdown(self):
        mt5.shutdown()
        self.connected = False

    # -----------------------------
    # Market Data
    # -----------------------------
    def get_rates(self, symbol: str, timeframe, n: int = 180) -> Optional[Dict]:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n)
        if rates is None:
            return None

        return {
            "open": [r["open"] for r in rates],
            "high": [r["high"] for r in rates],
            "low": [r["low"] for r in rates],
            "close": [r["close"] for r in rates],
            "timestamp": [r["time"] for r in rates],
        }

    def get_tick(self, symbol: str):
        return mt5.symbol_info_tick(symbol)

    def get_spread(self, symbol: str) -> float:
        tick = self.get_tick(symbol)
        info = mt5.symbol_info(symbol)

        if not tick or not info or not tick.ask or not tick.bid:
            return float("inf")

        return (tick.ask - tick.bid) / info.point

    # -----------------------------
    # Trading
    # -----------------------------
    def send_order(
            self, 
            symbol: str, 
            direction: str, 
            volume: float,
            magic: int = 999999,
            comment: str = "forward_test"
        ):

        tick = self.get_tick(symbol)

        if direction == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": 10,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print("Order failed:", result)
        else:
            print("Order success:", result)

        return result

    def close_position(self, position):
        tick = self.get_tick(position.symbol)

        if position.type == mt5.POSITION_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": order_type,
            "position": position.ticket,
            "price": price,
            "deviation": 10,
            "magic": 999999,
            "comment": "close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        return mt5.order_send(request)

    # -----------------------------
    # Positions
    # -----------------------------
    def get_positions(self, symbol: str):
        return mt5.positions_get(symbol=symbol)
    
    def history_deals_get(self, ticket):
        return mt5.history_deals_get(ticket=ticket)
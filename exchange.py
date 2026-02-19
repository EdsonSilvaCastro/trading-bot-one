"""
===============================================================================
BYBIT EXCHANGE CONNECTOR
===============================================================================
Handles all communication with Bybit API (testnet & mainnet).
Uses pybit v5 SDK for REST API calls.
===============================================================================
"""

import logging
import time
from typing import Optional, Dict, Tuple
from pybit.unified_trading import HTTP
from datetime import datetime, timedelta
import pandas as pd

logger = logging.getLogger("fvg_bot.exchange")


class BybitConnector:
    """
    Bybit V5 API connector for futures trading.
    Supports both testnet and mainnet.
    """
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True, demo: bool = False):
        self.testnet = testnet
        self.demo = demo
        self.session = HTTP(
            testnet=testnet,
            demo=demo,
            api_key=api_key,
            api_secret=api_secret,
        )
        
        if demo:
            env = "DEMO TRADING"
        elif testnet:
            env = "TESTNET"
        else:
            env = "⚠️  MAINNET"
        logger.info(f"Connected to Bybit {env}")
        
        # Verify connection
        try:
            server_time = self.session.get_server_time()
            if server_time["retCode"] == 0:
                logger.info("  ✅ Connection verified")
            else:
                logger.error(f"  ❌ Connection failed: {server_time['retMsg']}")
        except Exception as e:
            logger.error(f"  ❌ Connection error: {e}")
    
    # ======================== ACCOUNT ========================
    
    def get_balance(self) -> Dict:
        """Get USDT balance from unified account"""
        try:
            result = self.session.get_wallet_balance(
                accountType="UNIFIED",
                coin="USDT",
            )
            if result["retCode"] == 0:
                accounts = result["result"]["list"]
                if accounts:
                    for coin in accounts[0].get("coin", []):
                        if coin["coin"] == "USDT":
                            return {
                                "total": float(coin["walletBalance"] or 0),
                                "available": float(coin["availableToWithdraw"] or 0),
                                "unrealized_pnl": float(coin.get("unrealisedPnl", 0) or 0),
                            }
            logger.warning(f"Could not get balance: {result.get('retMsg', 'Unknown error')}")
            return {"total": 0, "available": 0, "unrealized_pnl": 0}
        except Exception as e:
            logger.error(f"Balance error: {e}")
            return {"total": 0, "available": 0, "unrealized_pnl": 0}
    
    # ======================== MARKET DATA ========================
    
    def get_klines(self, symbol: str, interval: str, limit: int = 220) -> pd.DataFrame:
        """
        Fetch kline/candlestick data.
        
        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            interval: Candle interval ("240" for 4H)
            limit: Number of candles (max 1000)
        
        Returns:
            DataFrame with [timestamp, open, high, low, close, volume]
        """
        try:
            result = self.session.get_kline(
                category="linear",
                symbol=symbol,
                interval=interval,
                limit=limit,
            )
            
            if result["retCode"] != 0:
                logger.error(f"Kline error: {result['retMsg']}")
                return pd.DataFrame()
            
            rows = result["result"]["list"]
            if not rows:
                return pd.DataFrame()
            
            df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"])
            df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
            
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float)
            
            df = df[["timestamp", "open", "high", "low", "close", "volume"]]
            df = df.sort_values("timestamp").reset_index(drop=True)
            
            return df
        
        except Exception as e:
            logger.error(f"Kline fetch error: {e}")
            return pd.DataFrame()
    
    def get_ticker(self, symbol: str) -> Dict:
        """Get current ticker data (last price, 24h volume, etc.)"""
        try:
            result = self.session.get_tickers(
                category="linear",
                symbol=symbol,
            )
            if result["retCode"] == 0 and result["result"]["list"]:
                ticker = result["result"]["list"][0]
                return {
                    "last_price": float(ticker["lastPrice"]),
                    "mark_price": float(ticker["markPrice"]),
                    "index_price": float(ticker["indexPrice"]),
                    "volume_24h": float(ticker["volume24h"]),
                    "funding_rate": float(ticker.get("fundingRate", 0)),
                    "next_funding_time": ticker.get("nextFundingTime", ""),
                }
            return {}
        except Exception as e:
            logger.error(f"Ticker error: {e}")
            return {}
    
    # ======================== TRADING ========================
    
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a symbol"""
        try:
            result = self.session.set_leverage(
                category="linear",
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage),
            )
            if result["retCode"] == 0 or "not modified" in result.get("retMsg", "").lower():
                logger.info(f"  Leverage set to {leverage}x for {symbol}")
                return True
            logger.warning(f"  Leverage error: {result['retMsg']}")
            return False
        except Exception as e:
            logger.error(f"Leverage error: {e}")
            return False
    
    def set_margin_mode(self, symbol: str, mode: str = "ISOLATED") -> bool:
        """Set margin mode (ISOLATED or CROSS)"""
        try:
            trade_mode = 1 if mode == "ISOLATED" else 0
            result = self.session.switch_margin_mode(
                category="linear",
                symbol=symbol,
                tradeMode=trade_mode,
                buyLeverage="3",
                sellLeverage="3",
            )
            if result["retCode"] == 0 or "not modified" in result.get("retMsg", "").lower():
                logger.info(f"  Margin mode set to {mode} for {symbol}")
                return True
            logger.warning(f"  Margin mode error: {result['retMsg']}")
            return False
        except Exception as e:
            logger.error(f"Margin mode error: {e}")
            return False
    
    def place_limit_order(self, symbol: str, side: str, qty: float, 
                          price: float, sl: float, tp: float,
                          reduce_only: bool = False) -> Optional[str]:
        """
        Place a limit order with SL and TP.
        
        Args:
            symbol: Trading pair
            side: "Buy" or "Sell"
            qty: Order quantity
            price: Limit price
            sl: Stop loss price
            tp: Take profit price
            reduce_only: If True, only reduces position
        
        Returns:
            Order ID if successful, None otherwise.
        """
        try:
            order_params = {
                "category": "linear",
                "symbol": symbol,
                "side": side,
                "orderType": "Limit",
                "qty": str(round(qty, 4)),
                "price": str(round(price, 2)),
                "stopLoss": str(round(sl, 2)),
                "takeProfit": str(round(tp, 2)),
                "slTriggerBy": "MarkPrice",
                "tpTriggerBy": "MarkPrice",
                "timeInForce": "GTC",
                "reduceOnly": reduce_only,
            }
            
            result = self.session.place_order(**order_params)
            
            if result["retCode"] == 0:
                order_id = result["result"]["orderId"]
                logger.info(f"  📝 Order placed: {side} {qty} {symbol} @ {price}")
                logger.info(f"     SL: {sl} | TP: {tp} | OrderID: {order_id}")
                return order_id
            else:
                logger.error(f"  ❌ Order failed: {result['retMsg']}")
                return None
        
        except Exception as e:
            logger.error(f"Order error: {e}")
            return None
    
    def place_market_order(self, symbol: str, side: str, qty: float,
                           sl: float = None, tp: float = None,
                           reduce_only: bool = False) -> Optional[str]:
        """Place a market order (for immediate fills)"""
        try:
            order_params = {
                "category": "linear",
                "symbol": symbol,
                "side": side,
                "orderType": "Market",
                "qty": str(round(qty, 4)),
                "timeInForce": "GTC",
                "reduceOnly": reduce_only,
            }
            
            if sl:
                order_params["stopLoss"] = str(round(sl, 2))
                order_params["slTriggerBy"] = "MarkPrice"
            if tp:
                order_params["takeProfit"] = str(round(tp, 2))
                order_params["tpTriggerBy"] = "MarkPrice"
            
            result = self.session.place_order(**order_params)
            
            if result["retCode"] == 0:
                order_id = result["result"]["orderId"]
                logger.info(f"  📝 Market order: {side} {qty} {symbol} | OrderID: {order_id}")
                return order_id
            else:
                logger.error(f"  ❌ Market order failed: {result['retMsg']}")
                return None
        
        except Exception as e:
            logger.error(f"Market order error: {e}")
            return None
    
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an open order"""
        try:
            result = self.session.cancel_order(
                category="linear",
                symbol=symbol,
                orderId=order_id,
            )
            if result["retCode"] == 0:
                logger.info(f"  🚫 Order cancelled: {order_id}")
                return True
            logger.warning(f"  Cancel failed: {result['retMsg']}")
            return False
        except Exception as e:
            logger.error(f"Cancel error: {e}")
            return False
    
    def cancel_all_orders(self, symbol: str) -> bool:
        """Cancel all open orders for a symbol"""
        try:
            result = self.session.cancel_all_orders(
                category="linear",
                symbol=symbol,
            )
            if result["retCode"] == 0:
                logger.info(f"  🚫 All orders cancelled for {symbol}")
                return True
            return False
        except Exception as e:
            logger.error(f"Cancel all error: {e}")
            return False
    
    # ======================== POSITIONS ========================
    
    def get_position(self, symbol: str) -> Optional[Dict]:
        """Get current open position for a symbol"""
        try:
            result = self.session.get_positions(
                category="linear",
                symbol=symbol,
            )
            if result["retCode"] == 0:
                positions = result["result"]["list"]
                for pos in positions:
                    size = float(pos["size"])
                    if size > 0:
                        return {
                            "symbol": pos["symbol"],
                            "side": pos["side"],
                            "size": size,
                            "entry_price": float(pos["avgPrice"]),
                            "mark_price": float(pos["markPrice"]),
                            "unrealized_pnl": float(pos["unrealisedPnl"]),
                            "leverage": pos["leverage"],
                            "liq_price": float(pos["liqPrice"]) if pos["liqPrice"] else 0,
                            "stop_loss": float(pos["stopLoss"]) if pos["stopLoss"] else 0,
                            "take_profit": float(pos["takeProfit"]) if pos["takeProfit"] else 0,
                        }
            return None
        except Exception as e:
            logger.error(f"Position error: {e}")
            return None
    
    def close_position(self, symbol: str, side: str, qty: float) -> Optional[str]:
        """Close a position with a market order"""
        close_side = "Sell" if side == "Buy" else "Buy"
        return self.place_market_order(symbol, close_side, qty, reduce_only=True)
    
    # ======================== ORDER STATUS ========================
    
    def get_open_orders(self, symbol: str) -> list:
        """Get all open orders for a symbol"""
        try:
            result = self.session.get_open_orders(
                category="linear",
                symbol=symbol,
            )
            if result["retCode"] == 0:
                return result["result"]["list"]
            return []
        except Exception as e:
            logger.error(f"Open orders error: {e}")
            return []
    
    def get_order_status(self, symbol: str, order_id: str) -> Optional[Dict]:
        """Get status of a specific order"""
        try:
            result = self.session.get_order_history(
                category="linear",
                symbol=symbol,
                orderId=order_id,
            )
            if result["retCode"] == 0 and result["result"]["list"]:
                order = result["result"]["list"][0]
                return {
                    "order_id": order["orderId"],
                    "status": order["orderStatus"],
                    "side": order["side"],
                    "price": float(order["price"]),
                    "qty": float(order["qty"]),
                    "filled_qty": float(order.get("cumExecQty", 0)),
                    "avg_price": float(order.get("avgPrice", 0)),
                }
            return None
        except Exception as e:
            logger.error(f"Order status error: {e}")
            return None
    
    # ======================== INSTRUMENT INFO ========================
    
    def get_instrument_info(self, symbol: str) -> Dict:
        """Get instrument specifications (min qty, tick size, etc.)"""
        try:
            result = self.session.get_instruments_info(
                category="linear",
                symbol=symbol,
            )
            if result["retCode"] == 0 and result["result"]["list"]:
                inst = result["result"]["list"][0]
                lot_filter = inst.get("lotSizeFilter", {})
                price_filter = inst.get("priceFilter", {})
                return {
                    "symbol": inst["symbol"],
                    "min_qty": float(lot_filter.get("minOrderQty", 0.001)),
                    "max_qty": float(lot_filter.get("maxOrderQty", 100)),
                    "qty_step": float(lot_filter.get("qtyStep", 0.001)),
                    "tick_size": float(price_filter.get("tickSize", 0.01)),
                    "min_price": float(price_filter.get("minPrice", 0.1)),
                    "max_leverage": float(inst.get("leverageFilter", {}).get("maxLeverage", 100)),
                }
            return {}
        except Exception as e:
            logger.error(f"Instrument info error: {e}")
            return {}
    
    def round_qty(self, qty: float, qty_step: float) -> float:
        """Round quantity to valid step size"""
        if qty_step <= 0:
            return qty
        return round(qty / qty_step) * qty_step
    
    def round_price(self, price: float, tick_size: float) -> float:
        """Round price to valid tick size"""
        if tick_size <= 0:
            return price
        return round(price / tick_size) * tick_size

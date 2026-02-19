"""
===============================================================================
FVG BOT — MAIN ORCHESTRATOR
===============================================================================
Paper trading bot for Bybit testnet.
Strategy: V2 — FVG + Trend (EMA200) on BTC/USDT 4H

This is the main loop that:
1. Fetches candles from Bybit
2. Runs the FVG strategy engine
3. Places/manages orders via the Bybit connector
4. Logs everything for analysis
===============================================================================

USAGE:
    1. Get Bybit testnet API keys from https://testnet.bybit.com
    2. Edit config.json with your keys
    3. Run: python bot.py

===============================================================================
"""

import json
import time
import logging
import os
import csv
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path

from strategy import FVGStrategyEngine, FVGSignal
from exchange import BybitConnector

# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging(config: dict):
    """Configure logging to both console and file"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    log_level = getattr(logging, config.get("logging", {}).get("level", "INFO"))
    
    # Root logger for the bot
    logger = logging.getLogger("fvg_bot")
    logger.setLevel(log_level)
    
    # Console handler with colors
    console = logging.StreamHandler()
    console.setLevel(log_level)
    fmt = logging.Formatter("%(asctime)s | %(message)s", datefmt="%H:%M:%S")
    console.setFormatter(fmt)
    logger.addHandler(console)
    
    # File handler
    log_file = config.get("logging", {}).get("file", "logs/bot.log")
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter("%(asctime)s | %(name)s | %(levelname)s | %(message)s")
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)
    
    return logger


# ============================================================================
# TRADE LOGGER (CSV)
# ============================================================================

class TradeLogger:
    """Logs completed trades to CSV for analysis"""
    
    def __init__(self, filepath: str = "logs/trades.csv"):
        self.filepath = filepath
        Path(filepath).parent.mkdir(exist_ok=True)
        
        # Create file with headers if it doesn't exist
        if not os.path.exists(filepath):
            with open(filepath, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "direction", "entry_price", "exit_price",
                    "stop_loss", "take_profit", "result", "pnl_pct", "pnl_usd",
                    "position_size", "duration_min", "fvg_size_pct", "sl_pct",
                ])
    
    def log_trade(self, trade_result, position_size_usd: float = 0):
        """Append a trade to the CSV log"""
        sig = trade_result.signal
        with open(self.filepath, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(),
                sig.direction,
                round(sig.entry_price, 2),
                round(trade_result.exit_price, 2),
                round(sig.stop_loss, 2),
                round(sig.take_profit, 2),
                trade_result.result,
                round(trade_result.pnl_pct * 100, 4),
                round(trade_result.pnl_usd, 2),
                round(position_size_usd, 2),
                round(trade_result.duration_minutes, 1),
                round(sig.fvg_size_pct * 100, 4),
                round(sig.sl_pct * 100, 4),
            ])


# ============================================================================
# RISK MANAGER
# ============================================================================

class RiskManager:
    """Monitors risk limits and can trigger kill switch"""
    
    def __init__(self, config: dict, initial_balance: float):
        self.config = config.get("risk", {})
        self.initial_balance = initial_balance
        self.daily_pnl = 0
        self.daily_reset_time = datetime.now().replace(hour=0, minute=0, second=0)
        self.killed = False
        
        self.max_daily_loss = self.config.get("max_daily_loss_pct", 0.05)
        self.max_drawdown = self.config.get("max_drawdown_pct", 0.15)
        self.kill_switch = self.config.get("kill_switch_loss_pct", 0.20)
    
    def check(self, current_balance: float, trade_pnl: float = 0) -> Tuple[bool, str]:
        """
        Check if trading should continue.
        Returns (safe_to_trade, reason)
        """
        if self.killed:
            return False, "KILL SWITCH ACTIVATED"
        
        # Reset daily PnL at midnight UTC
        now = datetime.now()
        if now.date() > self.daily_reset_time.date():
            self.daily_pnl = 0
            self.daily_reset_time = now.replace(hour=0, minute=0, second=0)
        
        self.daily_pnl += trade_pnl
        
        # Check daily loss limit
        if self.initial_balance > 0:
            daily_loss_pct = abs(self.daily_pnl) / self.initial_balance
            if self.daily_pnl < 0 and daily_loss_pct >= self.max_daily_loss:
                return False, f"Daily loss limit reached: {daily_loss_pct*100:.1f}%"
        
        # Check total drawdown
        if self.initial_balance > 0:
            drawdown = (self.initial_balance - current_balance) / self.initial_balance
            if drawdown >= self.max_drawdown:
                return False, f"Max drawdown reached: {drawdown*100:.1f}%"
            
            # Kill switch
            if drawdown >= self.kill_switch:
                self.killed = True
                return False, f"KILL SWITCH: {drawdown*100:.1f}% drawdown"
        
        return True, "OK"


# Need this import for type hint
from typing import Tuple


# ============================================================================
# MAIN BOT
# ============================================================================

class FVGBot:
    """
    Main bot orchestrator.
    Connects strategy engine with exchange connector.
    """
    
    def __init__(self, config_path: str = "config.json"):
        # Load config
        with open(config_path) as f:
            self.config = json.load(f)
        
        # Setup logging
        self.logger = setup_logging(self.config)
        self.logger.info("=" * 60)
        self.logger.info("  FVG BOT — V2: FVG + Trend (EMA200)")
        self.logger.info(f"  {'TESTNET' if self.config['exchange']['testnet'] else '⚠️  MAINNET'}")
        self.logger.info("=" * 60)
        
        # Initialize components
        self.exchange = BybitConnector(
            api_key=self.config["exchange"]["api_key"],
            api_secret=self.config["exchange"]["api_secret"],
            testnet=self.config["exchange"]["testnet"],
        )
        
        self.strategy = FVGStrategyEngine(self.config["strategy"])
        self.trade_logger = TradeLogger(self.config.get("logging", {}).get("trade_log", "logs/trades.csv"))
        
        # Trading params
        self.symbol = self.config["trading"]["symbol"]
        self.interval = self.config["trading"]["interval"]
        self.leverage = self.config["trading"]["leverage"]
        self.position_size_pct = self.config["trading"]["position_size_pct"]
        
        # Get instrument info
        self.instrument = self.exchange.get_instrument_info(self.symbol)
        self.logger.info(f"  Instrument: {self.symbol}")
        self.logger.info(f"  Min qty: {self.instrument.get('min_qty', 'N/A')} | Tick: {self.instrument.get('tick_size', 'N/A')}")
        
        # Setup leverage and margin
        self.exchange.set_leverage(self.symbol, self.leverage)
        self.exchange.set_margin_mode(self.symbol, self.config["trading"].get("margin_mode", "ISOLATED"))
        
        # Get initial balance
        balance = self.exchange.get_balance()
        self.initial_balance = balance["total"]
        self.logger.info(f"  Balance: {self.initial_balance:.2f} USDT")
        
        # Risk manager
        self.risk_manager = RiskManager(self.config, self.initial_balance)
        
        # State
        self.running = True
        self.current_order_id = None
        self.candle_count = 0
        self.last_candle_time = None
        
        # Graceful shutdown
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)
    
    def _shutdown(self, signum, frame):
        """Handle graceful shutdown"""
        self.logger.info("\n⚠️  Shutdown signal received...")
        self.running = False
    
    def calculate_position_size(self, entry_price: float) -> float:
        """Calculate position size based on account balance and risk parameters"""
        balance = self.exchange.get_balance()
        available = balance["available"]
        
        # Risk-based position size: risk X% of account per trade
        risk_amount = available * self.position_size_pct
        position_value = risk_amount * self.leverage
        qty = position_value / entry_price
        
        # Round to valid step
        qty_step = self.instrument.get("qty_step", 0.001)
        qty = self.exchange.round_qty(qty, qty_step)
        
        # Ensure above minimum
        min_qty = self.instrument.get("min_qty", 0.001)
        if qty < min_qty:
            self.logger.warning(f"Position size {qty} below minimum {min_qty}")
            qty = min_qty
        
        self.logger.info(f"  Position size: {qty} BTC (${position_value:.2f} notional, {self.leverage}x leverage)")
        return qty
    
    def run(self):
        """Main bot loop"""
        self.logger.info("\n🚀 Bot starting...")
        self.logger.info(f"   Symbol: {self.symbol} | Interval: {self.interval}m | Leverage: {self.leverage}x")
        self.logger.info(f"   Strategy: V2 FVG + Trend (EMA200)")
        self.logger.info(f"   Risk per trade: {self.position_size_pct*100}% of balance")
        self.logger.info(f"   Paper trading: {'Yes' if self.config['exchange']['testnet'] else 'NO - REAL MONEY'}")
        self.logger.info("-" * 60)
        
        # Calculate sleep time based on interval
        # For 4H candles, we check every 5 minutes for price updates
        # and do full analysis every new candle
        check_interval_seconds = 300  # 5 minutes
        candle_interval_seconds = int(self.interval) * 60
        
        last_full_check = 0
        
        while self.running:
            try:
                now = time.time()
                
                # ===== RISK CHECK =====
                balance = self.exchange.get_balance()
                safe, reason = self.risk_manager.check(balance["total"])
                if not safe:
                    self.logger.warning(f"🛑 RISK LIMIT: {reason}")
                    self._emergency_close()
                    self.logger.info("Bot paused due to risk limits. Will resume next day or restart manually.")
                    time.sleep(3600)  # Sleep 1 hour
                    continue
                
                # ===== CHECK EXISTING POSITION =====
                position = self.exchange.get_position(self.symbol)
                if position:
                    self._monitor_position(position)
                
                # ===== FULL CANDLE ANALYSIS (every new candle) =====
                if now - last_full_check >= candle_interval_seconds or last_full_check == 0:
                    self.logger.info(f"\n📊 Candle analysis at {datetime.now().strftime('%Y-%m-%d %H:%M')}")
                    
                    # Fetch candles
                    df = self.exchange.get_klines(self.symbol, self.interval, limit=250)
                    
                    if df.empty or len(df) < 210:
                        self.logger.warning(f"Not enough candle data: {len(df)} candles")
                        time.sleep(60)
                        continue
                    
                    self.candle_count = len(df)
                    latest = df.iloc[-1]
                    self.last_candle_time = latest["timestamp"]
                    
                    self.logger.info(f"   Latest candle: {latest['timestamp']} | Close: {latest['close']:.2f}")
                    self.logger.info(f"   Balance: {balance['total']:.2f} USDT | PnL: {balance['unrealized_pnl']:.2f}")
                    
                    # Cancel expired signals
                    self.strategy.cancel_expired_signals(self.candle_count)
                    
                    # Run strategy — check for new FVG
                    if not position and not self.current_order_id:
                        new_signal = self.strategy.update_candles(df)
                        
                        if new_signal:
                            self._place_entry_order(new_signal)
                    
                    # Print stats
                    stats = self.strategy.get_stats()
                    if stats["trades"] > 0:
                        self.logger.info(f"   📈 Stats: {stats['trades']} trades | WR: {stats['win_rate']:.1f}% | PnL: {stats['total_pnl_pct']:.2f}%")
                    
                    last_full_check = now
                
                # ===== QUICK PRICE CHECK (every 5 min) =====
                else:
                    ticker = self.exchange.get_ticker(self.symbol)
                    if ticker:
                        current_price = ticker["last_price"]
                        
                        # Check if pending signal should be filled
                        active_pos = self.strategy.get_active_position()
                        if not active_pos:
                            filled = self.strategy.check_pending_fills(current_price, datetime.now())
                            if filled:
                                self.logger.info(f"   Price {current_price:.2f} reached entry zone")
                        
                        # Check if any pending orders were filled on exchange
                        if self.current_order_id and not position:
                            self._check_order_status()
                
                # Sleep
                time.sleep(check_interval_seconds)
            
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"❌ Error in main loop: {e}", exc_info=True)
                time.sleep(60)  # Wait a minute on error
        
        self._cleanup()
    
    def _place_entry_order(self, signal: FVGSignal):
        """Place a limit order for a new FVG signal"""
        qty = self.calculate_position_size(signal.entry_price)
        
        side = "Buy" if signal.direction == "LONG" else "Sell"
        
        # Round prices to tick size
        tick = self.instrument.get("tick_size", 0.01)
        entry = self.exchange.round_price(signal.entry_price, tick)
        sl = self.exchange.round_price(signal.stop_loss, tick)
        tp = self.exchange.round_price(signal.take_profit, tick)
        
        order_id = self.exchange.place_limit_order(
            symbol=self.symbol,
            side=side,
            qty=qty,
            price=entry,
            sl=sl,
            tp=tp,
        )
        
        if order_id:
            signal.order_id = order_id
            self.current_order_id = order_id
            self.logger.info(f"  ✅ Entry order placed: {signal.direction} @ {entry}")
        else:
            self.logger.error("  ❌ Failed to place entry order")
            signal.status = "cancelled"
    
    def _check_order_status(self):
        """Check if pending entry order was filled"""
        if not self.current_order_id:
            return
        
        orders = self.exchange.get_open_orders(self.symbol)
        order_exists = any(o["orderId"] == self.current_order_id for o in orders)
        
        if not order_exists:
            # Order no longer open — either filled or cancelled
            status = self.exchange.get_order_status(self.symbol, self.current_order_id)
            if status and status["status"] == "Filled":
                self.logger.info(f"  ✅ Entry order FILLED @ {status['avg_price']}")
                # The position is now managed by exchange SL/TP
                self.current_order_id = None
            elif status and status["status"] in ["Cancelled", "Rejected"]:
                self.logger.info(f"  🚫 Entry order {status['status']}")
                self.current_order_id = None
    
    def _monitor_position(self, position: dict):
        """Monitor an open position"""
        pnl = position["unrealized_pnl"]
        pnl_pct = (pnl / (position["entry_price"] * position["size"])) * 100 if position["size"] > 0 else 0
        
        emoji = "🟢" if pnl >= 0 else "🔴"
        self.logger.debug(
            f"  {emoji} Position: {position['side']} {position['size']} @ {position['entry_price']:.2f} "
            f"| PnL: {pnl:+.2f} USDT ({pnl_pct:+.1f}%) "
            f"| Liq: {position['liq_price']:.2f}"
        )
    
    def _emergency_close(self):
        """Emergency close all positions and cancel all orders"""
        self.logger.warning("🚨 EMERGENCY CLOSE")
        
        # Cancel all orders
        self.exchange.cancel_all_orders(self.symbol)
        self.current_order_id = None
        
        # Close position if exists
        position = self.exchange.get_position(self.symbol)
        if position:
            self.exchange.close_position(self.symbol, position["side"], position["size"])
    
    def _cleanup(self):
        """Cleanup on bot shutdown"""
        self.logger.info("\n" + "=" * 60)
        self.logger.info("  BOT SHUTTING DOWN")
        self.logger.info("=" * 60)
        
        # Print final stats
        stats = self.strategy.get_stats()
        if stats["trades"] > 0:
            self.logger.info(f"  Total trades: {stats['trades']}")
            self.logger.info(f"  Win rate: {stats['win_rate']:.1f}%")
            self.logger.info(f"  Total PnL: {stats['total_pnl_pct']:.2f}%")
        
        balance = self.exchange.get_balance()
        self.logger.info(f"  Final balance: {balance['total']:.2f} USDT")
        self.logger.info(f"  Starting balance: {self.initial_balance:.2f} USDT")
        
        if self.initial_balance > 0:
            total_return = (balance["total"] - self.initial_balance) / self.initial_balance * 100
            self.logger.info(f"  Total return: {total_return:+.2f}%")
        
        # Ask about open positions
        position = self.exchange.get_position(self.symbol)
        if position:
            self.logger.warning(f"  ⚠️  Open position remains: {position['side']} {position['size']} BTC")
            self.logger.warning(f"     The position SL/TP will still be active on Bybit.")
        
        if self.current_order_id:
            self.logger.warning(f"  ⚠️  Pending order remains: {self.current_order_id}")
            self.logger.warning(f"     Consider cancelling it on Bybit.")
        
        self.logger.info("\n  Goodbye! 👋")


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="FVG Trading Bot — Bybit")
    parser.add_argument("--config", default="config.json", help="Path to config file")
    parser.add_argument("--dry-run", action="store_true", help="Print config and exit")
    args = parser.parse_args()
    
    if args.dry_run:
        with open(args.config) as f:
            config = json.load(f)
        print(json.dumps(config, indent=2))
        print("\n✅ Config is valid. Remove --dry-run to start the bot.")
        sys.exit(0)
    
    bot = FVGBot(config_path=args.config)
    bot.run()

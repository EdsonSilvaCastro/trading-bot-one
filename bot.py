"""
===============================================================================
FVG BOT — MAIN ORCHESTRATOR
===============================================================================
Paper trading bot for Bybit (Demo Trading / Testnet / Live).
Strategy: V2 — FVG + Trend (EMA200) on BTC/USDT 4H

USAGE:
    1. Edit config.json with your API keys and Telegram settings
    2. python bot.py              # Run the bot
    3. python bot.py --dry-run    # Validate config without running
===============================================================================
"""

from typing import Tuple, Optional
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
from telegram_notifier import TelegramNotifier


# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging(config: dict):
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    log_level = getattr(logging, config.get("logging", {}).get("level", "INFO"))
    
    logger = logging.getLogger("fvg_bot")
    logger.setLevel(log_level)
    
    console = logging.StreamHandler()
    console.setLevel(log_level)
    fmt = logging.Formatter("%(asctime)s | %(message)s", datefmt="%H:%M:%S")
    console.setFormatter(fmt)
    logger.addHandler(console)
    
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
    def __init__(self, filepath: str = "logs/trades.csv"):
        self.filepath = filepath
        Path(filepath).parent.mkdir(exist_ok=True)
        
        if not os.path.exists(filepath):
            with open(filepath, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "direction", "entry_price", "exit_price",
                    "stop_loss", "take_profit", "result", "pnl_pct", "pnl_usd",
                    "position_size", "duration_min", "fvg_size_pct", "sl_pct",
                ])
    
    def log_trade(self, trade_result, position_size_usd: float = 0):
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
        if self.killed:
            return False, "KILL SWITCH ACTIVATED"
        
        now = datetime.now()
        if now.date() > self.daily_reset_time.date():
            self.daily_pnl = 0
            self.daily_reset_time = now.replace(hour=0, minute=0, second=0)
        
        self.daily_pnl += trade_pnl
        
        if self.initial_balance > 0:
            daily_loss_pct = abs(self.daily_pnl) / self.initial_balance
            if self.daily_pnl < 0 and daily_loss_pct >= self.max_daily_loss:
                return False, f"Daily loss limit reached: {daily_loss_pct*100:.1f}%"
        
        if self.initial_balance > 0:
            drawdown = (self.initial_balance - current_balance) / self.initial_balance
            if drawdown >= self.max_drawdown:
                return False, f"Max drawdown reached: {drawdown*100:.1f}%"
            if drawdown >= self.kill_switch:
                self.killed = True
                return False, f"KILL SWITCH: {drawdown*100:.1f}% drawdown"
        
        return True, "OK"


# ============================================================================
# MAIN BOT
# ============================================================================

class FVGBot:
    def __init__(self, config_path: str = "config.json"):
        with open(config_path) as f:
            self.config = json.load(f)
        
        self.logger = setup_logging(self.config)
        
        # Determine mode
        exchange_cfg = self.config["exchange"]
        self.is_demo = exchange_cfg.get("demo", False)
        self.is_testnet = exchange_cfg.get("testnet", False)
        
        if self.is_demo:
            mode_str = "DEMO TRADING"
        elif self.is_testnet:
            mode_str = "TESTNET"
        else:
            mode_str = "⚠️  LIVE TRADING"
        
        self.logger.info("=" * 60)
        self.logger.info("  FVG BOT — V2: FVG + Trend (EMA200)")
        self.logger.info(f"  {mode_str}")
        self.logger.info("=" * 60)
        
        # Initialize exchange
        self.exchange = BybitConnector(
            api_key=exchange_cfg["api_key"],
            api_secret=exchange_cfg["api_secret"],
            testnet=self.is_testnet and not self.is_demo,
            demo=self.is_demo,
        )
        
        # Initialize strategy
        self.strategy = FVGStrategyEngine(self.config["strategy"])
        self.trade_logger = TradeLogger(self.config.get("logging", {}).get("trade_log", "logs/trades.csv"))
        
        # Initialize Telegram
        tg_config = self.config.get("notifications", {})
        self.telegram = TelegramNotifier(
            token=tg_config.get("telegram_token", ""),
            chat_id=tg_config.get("telegram_chat_id", ""),
            enabled=tg_config.get("enabled", False),
        )
        
        # Trading params
        self.symbol = self.config["trading"]["symbol"]
        self.interval = self.config["trading"]["interval"]
        self.leverage = self.config["trading"]["leverage"]
        self.position_size_pct = self.config["trading"]["position_size_pct"]
        
        # Instrument info
        self.instrument = self.exchange.get_instrument_info(self.symbol)
        self.logger.info(f"  Instrument: {self.symbol}")
        self.logger.info(f"  Min qty: {self.instrument.get('min_qty', 'N/A')} | Tick: {self.instrument.get('tick_size', 'N/A')}")
        
        # Setup leverage and margin
        self.exchange.set_leverage(self.symbol, self.leverage)
        margin_mode = self.config["trading"].get("margin_mode", "ISOLATED")
        self.exchange.set_margin_mode(self.symbol, margin_mode)
        
        # Initial balance
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
        self.last_daily_summary = None
        
        # Graceful shutdown
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)
    
    def _shutdown(self, signum, frame):
        self.logger.info("\n⚠️  Shutdown signal received...")
        self.telegram.bot_stopped("Shutdown signal received")
        self.running = False
    
    def calculate_position_size(self, entry_price: float) -> float:
        balance = self.exchange.get_balance()
        available = balance["available"]
        
        risk_amount = available * self.position_size_pct
        position_value = risk_amount * self.leverage
        qty = position_value / entry_price
        
        qty_step = self.instrument.get("qty_step", 0.001)
        qty = self.exchange.round_qty(qty, qty_step)
        
        min_qty = self.instrument.get("min_qty", 0.001)
        if qty < min_qty:
            self.logger.warning(f"Position size {qty} below minimum {min_qty}")
            qty = min_qty
        
        self.logger.info(f"  Position size: {qty} BTC (${position_value:.2f} notional, {self.leverage}x leverage)")
        return qty
    
    def run(self):
        self.logger.info(f"\n🚀 Bot starting...")
        self.logger.info(f"   Symbol: {self.symbol} | Interval: {self.interval}m | Leverage: {self.leverage}x")
        self.logger.info(f"   Strategy: V2 FVG + Trend (EMA200)")
        self.logger.info(f"   Risk per trade: {self.position_size_pct*100}% of balance")
        self.logger.info(f"   Telegram: {'Enabled' if self.telegram.enabled else 'Disabled'}")
        self.logger.info("-" * 60)
        
        check_interval_seconds = 300  # 5 min price checks
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
                    self.telegram.risk_alert(reason)
                    self._emergency_close()
                    time.sleep(3600)
                    continue
                
                # ===== CHECK EXISTING POSITION =====
                position = self.exchange.get_position(self.symbol)
                if position:
                    self._monitor_position(position)
                
                # ===== FULL CANDLE ANALYSIS =====
                if now - last_full_check >= candle_interval_seconds or last_full_check == 0:
                    self.logger.info(f"\n📊 Candle analysis at {datetime.now().strftime('%Y-%m-%d %H:%M')}")
                    
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
                    
                    # Check for new FVG
                    if not position and not self.current_order_id:
                        new_signal = self.strategy.update_candles(df)
                        
                        if new_signal:
                            # Telegram alert
                            self.telegram.signal_detected(
                                direction=new_signal.direction,
                                entry=new_signal.entry_price,
                                sl=new_signal.stop_loss,
                                tp=new_signal.take_profit,
                                sl_pct=new_signal.sl_pct,
                                tp_pct=new_signal.tp_pct,
                                fvg_size=new_signal.fvg_size_pct,
                                current_price=latest["close"],
                            )
                            self._place_entry_order(new_signal)
                    
                    # Stats
                    stats = self.strategy.get_stats()
                    if stats["trades"] > 0:
                        self.logger.info(f"   📈 Stats: {stats['trades']} trades | WR: {stats['win_rate']:.1f}% | PnL: {stats['total_pnl_pct']:.2f}%")
                    
                    # Daily summary (once per day around 00:00 UTC)
                    self._check_daily_summary(balance, stats, position)
                    
                    last_full_check = now
                
                # ===== QUICK PRICE CHECK =====
                else:
                    ticker = self.exchange.get_ticker(self.symbol)
                    if ticker:
                        current_price = ticker["last_price"]
                        
                        active_pos = self.strategy.get_active_position()
                        if not active_pos:
                            filled = self.strategy.check_pending_fills(current_price, datetime.now())
                            if filled:
                                self.logger.info(f"   Price {current_price:.2f} reached entry zone")
                        
                        if self.current_order_id and not position:
                            self._check_order_status()
                
                time.sleep(check_interval_seconds)
            
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"❌ Error in main loop: {e}", exc_info=True)
                self.telegram.error_alert(str(e))
                time.sleep(60)
        
        self._cleanup()
    
    def _place_entry_order(self, signal: FVGSignal):
        qty = self.calculate_position_size(signal.entry_price)
        side = "Buy" if signal.direction == "LONG" else "Sell"
        
        tick = self.instrument.get("tick_size", 0.01)
        entry = self.exchange.round_price(signal.entry_price, tick)
        sl = self.exchange.round_price(signal.stop_loss, tick)
        tp = self.exchange.round_price(signal.take_profit, tick)
        
        order_id = self.exchange.place_limit_order(
            symbol=self.symbol, side=side, qty=qty,
            price=entry, sl=sl, tp=tp,
        )
        
        if order_id:
            signal.order_id = order_id
            self.current_order_id = order_id
            
            margin = (qty * entry) / self.leverage
            self.telegram.order_placed(
                direction=signal.direction, qty=qty, entry=entry,
                sl=sl, tp=tp, leverage=self.leverage, margin=margin,
            )
            self.logger.info(f"  ✅ Entry order placed: {signal.direction} @ {entry}")
        else:
            self.logger.error("  ❌ Failed to place entry order")
            signal.status = "cancelled"
    
    def _check_order_status(self):
        if not self.current_order_id:
            return
        
        orders = self.exchange.get_open_orders(self.symbol)
        order_exists = any(o["orderId"] == self.current_order_id for o in orders)
        
        if not order_exists:
            status = self.exchange.get_order_status(self.symbol, self.current_order_id)
            if status and status["status"] == "Filled":
                self.logger.info(f"  ✅ Entry order FILLED @ {status['avg_price']}")
                self.current_order_id = None
            elif status and status["status"] in ["Cancelled", "Rejected"]:
                self.logger.info(f"  🚫 Entry order {status['status']}")
                self.current_order_id = None
    
    def _monitor_position(self, position: dict):
        pnl = position["unrealized_pnl"]
        pnl_pct = (pnl / (position["entry_price"] * position["size"])) * 100 if position["size"] > 0 else 0
        
        emoji = "🟢" if pnl >= 0 else "🔴"
        self.logger.debug(
            f"  {emoji} Position: {position['side']} {position['size']} @ {position['entry_price']:.2f} "
            f"| PnL: {pnl:+.2f} USDT ({pnl_pct:+.1f}%) "
            f"| Liq: {position['liq_price']:.2f}"
        )
    
    def _check_daily_summary(self, balance: dict, stats: dict, position):
        now = datetime.now()
        today = now.date()
        
        if self.last_daily_summary == today:
            return
        
        # Send daily summary at the first candle check of each day
        if now.hour >= 0:
            self.last_daily_summary = today
            self.telegram.daily_summary(
                balance=balance["total"],
                total_pnl_pct=stats.get("total_pnl_pct", 0),
                trades_today=0,
                wins=stats.get("wins", 0),
                losses=stats.get("losses", 0),
                active_position=position,
            )
    
    def _emergency_close(self):
        self.logger.warning("🚨 EMERGENCY CLOSE")
        self.exchange.cancel_all_orders(self.symbol)
        self.current_order_id = None
        
        position = self.exchange.get_position(self.symbol)
        if position:
            self.exchange.close_position(self.symbol, position["side"], position["size"])
    
    def _cleanup(self):
        self.logger.info("\n" + "=" * 60)
        self.logger.info("  BOT SHUTTING DOWN")
        self.logger.info("=" * 60)
        
        stats = self.strategy.get_stats()
        if stats["trades"] > 0:
            self.logger.info(f"  Total trades: {stats['trades']}")
            self.logger.info(f"  Win rate: {stats['win_rate']:.1f}%")
            self.logger.info(f"  Total PnL: {stats['total_pnl_pct']:.2f}%")
        
        balance = self.exchange.get_balance()
        self.logger.info(f"  Final balance: {balance['total']:.2f} USDT")
        
        position = self.exchange.get_position(self.symbol)
        if position:
            self.logger.warning(f"  ⚠️  Open position remains: {position['side']} {position['size']} BTC")
        
        self.telegram.bot_stopped(f"Final balance: ${balance['total']:.2f}")
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

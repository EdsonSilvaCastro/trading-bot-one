"""
===============================================================================
TELEGRAM NOTIFICATIONS MODULE
===============================================================================
Sends real-time alerts to Telegram when the bot:
- Detects a new FVG signal
- Opens a trade (order placed)
- Closes a trade (TP/SL hit)
- Encounters errors
- Sends daily summaries

SETUP:
1. Open Telegram, search @BotFather
2. Send /newbot and follow instructions → get your BOT TOKEN
3. Search @userinfobot → get your CHAT ID
4. Add both to config.json
===============================================================================
"""

import logging
import requests
from datetime import datetime
from typing import Optional

logger = logging.getLogger("fvg_bot.telegram")


class TelegramNotifier:
    """
    Sends formatted messages to a Telegram chat via Bot API.
    Fails silently — Telegram issues should never crash the bot.
    """
    
    def __init__(self, token: str, chat_id: str, enabled: bool = True):
        self.token = token
        self.chat_id = chat_id
        self.enabled = enabled and bool(token) and bool(chat_id)
        self.base_url = f"https://api.telegram.org/bot{token}"
        
        if self.enabled:
            # Test connection
            try:
                r = requests.get(f"{self.base_url}/getMe", timeout=10)
                data = r.json()
                if data.get("ok"):
                    bot_name = data["result"].get("username", "unknown")
                    logger.info(f"  📱 Telegram connected: @{bot_name}")
                    self.send_message("🤖 *FVG Bot started*\nConnected and monitoring BTC/USDT 4H")
                else:
                    logger.warning(f"  Telegram connection failed: {data}")
                    self.enabled = False
            except Exception as e:
                logger.warning(f"  Telegram init error: {e}")
                self.enabled = False
        else:
            logger.info("  📱 Telegram notifications: disabled")
    
    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Send a message to the configured chat"""
        if not self.enabled:
            return False
        
        try:
            r = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            return r.json().get("ok", False)
        except Exception as e:
            logger.debug(f"Telegram send error: {e}")
            return False
    
    # ======================== SIGNAL ALERTS ========================
    
    def signal_detected(self, direction: str, entry: float, sl: float, tp: float,
                        sl_pct: float, tp_pct: float, fvg_size: float, 
                        current_price: float):
        """Alert when a new FVG signal is detected"""
        emoji = "🟢" if direction == "LONG" else "🔴"
        arrow = "⬆️" if direction == "LONG" else "⬇️"
        
        msg = (
            f"{emoji} *NEW FVG SIGNAL: {direction}* {arrow}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📍 Entry: `${entry:,.2f}`\n"
            f"🛑 Stop Loss: `${sl:,.2f}` ({sl_pct*100:.2f}%)\n"
            f"🎯 Take Profit: `${tp:,.2f}` ({tp_pct*100:.2f}%)\n"
            f"📏 FVG Size: {fvg_size*100:.3f}%\n"
            f"💰 Current Price: `${current_price:,.2f}`\n"
            f"⏳ Waiting for price to reach entry..."
        )
        self.send_message(msg)
    
    def order_placed(self, direction: str, qty: float, entry: float, 
                     sl: float, tp: float, leverage: int, margin: float):
        """Alert when an order is placed on the exchange"""
        emoji = "📝"
        
        msg = (
            f"{emoji} *ORDER PLACED*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Direction: *{direction}*\n"
            f"Size: `{qty}` BTC\n"
            f"Entry: `${entry:,.2f}`\n"
            f"SL: `${sl:,.2f}` | TP: `${tp:,.2f}`\n"
            f"Leverage: {leverage}x\n"
            f"Margin used: `${margin:,.2f}`"
        )
        self.send_message(msg)
    
    def trade_opened(self, direction: str, entry_price: float, qty: float,
                     sl: float, tp: float):
        """Alert when an order is filled"""
        emoji = "✅"
        
        msg = (
            f"{emoji} *TRADE OPENED*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Direction: *{direction}*\n"
            f"Entry: `${entry_price:,.2f}`\n"
            f"Size: `{qty}` BTC\n"
            f"SL: `${sl:,.2f}` | TP: `${tp:,.2f}`"
        )
        self.send_message(msg)
    
    def trade_closed(self, direction: str, entry: float, exit_price: float,
                     pnl_pct: float, pnl_usd: float, result: str, 
                     duration_min: float):
        """Alert when a trade is closed"""
        if pnl_pct >= 0:
            emoji = "💰"
            result_text = "WIN"
        else:
            emoji = "📉"
            result_text = "LOSS"
        
        hours = int(duration_min // 60)
        mins = int(duration_min % 60)
        
        msg = (
            f"{emoji} *TRADE CLOSED — {result_text}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Direction: *{direction}*\n"
            f"Entry: `${entry:,.2f}`\n"
            f"Exit: `${exit_price:,.2f}`\n"
            f"Result: *{result}*\n"
            f"PnL: `{pnl_pct*100:+.2f}%` (`${pnl_usd:+,.2f}`)\n"
            f"Duration: {hours}h {mins}m"
        )
        self.send_message(msg)
    
    def signal_expired(self, direction: str, entry: float):
        """Alert when a signal expires (price never reached entry)"""
        msg = (
            f"⏰ *Signal Expired*\n"
            f"Direction: {direction} @ `${entry:,.2f}`\n"
            f"Price never reached entry zone."
        )
        self.send_message(msg)
    
    # ======================== STATUS UPDATES ========================
    
    def daily_summary(self, balance: float, total_pnl_pct: float, 
                      trades_today: int, wins: int, losses: int,
                      active_position: Optional[dict] = None):
        """Daily performance summary"""
        wr = (wins / trades_today * 100) if trades_today > 0 else 0
        
        pos_text = "None"
        if active_position:
            pos_text = (
                f"{active_position['side']} {active_position['size']} BTC "
                f"@ ${active_position['entry_price']:,.2f} "
                f"(PnL: ${active_position['unrealized_pnl']:+,.2f})"
            )
        
        msg = (
            f"📊 *DAILY SUMMARY*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Balance: `${balance:,.2f}`\n"
            f"📈 Total PnL: `{total_pnl_pct:+.2f}%`\n"
            f"📋 Trades today: {trades_today} (W:{wins} L:{losses})\n"
            f"🎯 Win rate: {wr:.0f}%\n"
            f"📍 Active position: {pos_text}\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}"
        )
        self.send_message(msg)
    
    def candle_update(self, price: float, balance: float, 
                      pending_signals: int, has_position: bool):
        """Periodic candle analysis update (optional, can be noisy)"""
        status = "📍 In position" if has_position else f"🔍 {pending_signals} pending signals" if pending_signals > 0 else "⏳ Scanning..."
        
        msg = (
            f"📊 *4H Candle Update*\n"
            f"BTC: `${price:,.2f}` | Balance: `${balance:,.2f}`\n"
            f"Status: {status}"
        )
        self.send_message(msg)
    
    # ======================== SYSTEM ALERTS ========================
    
    def error_alert(self, error_msg: str):
        """Alert on system errors"""
        msg = (
            f"⚠️ *SYSTEM ERROR*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"`{error_msg[:500]}`"
        )
        self.send_message(msg)
    
    def risk_alert(self, reason: str):
        """Alert when risk limits are hit"""
        msg = (
            f"🚨 *RISK ALERT*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{reason}\n"
            f"Bot has paused trading."
        )
        self.send_message(msg)
    
    def bot_stopped(self, reason: str = "Manual shutdown"):
        """Alert when bot stops"""
        msg = f"🛑 *Bot stopped*\n{reason}"
        self.send_message(msg)

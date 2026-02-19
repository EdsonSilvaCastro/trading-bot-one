"""
===============================================================================
FVG STRATEGY ENGINE — V2: FVG + Trend (EMA200)
===============================================================================
Core logic for detecting Fair Value Gaps and generating trade signals.
This module is exchange-agnostic — it only works with OHLCV data.
===============================================================================
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime
import logging

logger = logging.getLogger("fvg_bot.strategy")


@dataclass
class FVGSignal:
    """Represents a detected FVG with trade parameters"""
    signal_type: str          # "bullish" or "bearish"
    direction: str            # "LONG" or "SHORT"
    timestamp: datetime       # When the FVG was detected
    fvg_top: float            # Upper boundary of FVG
    fvg_bottom: float         # Lower boundary of FVG
    fvg_mid: float            # Midpoint of FVG
    entry_price: float        # Limit order price
    stop_loss: float          # Stop loss price
    take_profit: float        # Take profit price
    sl_pct: float             # SL distance as percentage
    tp_pct: float             # TP distance as percentage
    fvg_size_pct: float       # FVG size as percentage of price
    impulse_body_ratio: float # Body/range ratio of impulse candle
    trend_aligned: bool       # Whether trade aligns with EMA200 trend
    candle_idx: int           # Index of the third candle (FVG confirmed)
    status: str = "pending"   # pending, active, filled, cancelled, expired
    order_id: Optional[str] = None
    filled_at: Optional[float] = None
    filled_time: Optional[datetime] = None


@dataclass 
class TradeResult:
    """Result of a completed trade"""
    signal: FVGSignal
    exit_price: float
    exit_time: datetime
    pnl_pct: float
    pnl_usd: float
    result: str              # "TP", "SL", "MANUAL", "EXPIRED"
    duration_minutes: float
    fees_paid: float = 0.0


class FVGStrategyEngine:
    """
    Core strategy engine for FVG detection and signal generation.
    
    Strategy: V2 — FVG + Trend Filter (EMA200)
    - Detects Fair Value Gaps on 4H BTC/USDT candles
    - Only takes trades aligned with the EMA200 trend
    - Entry at the start of the FVG (conservative)
    - SL at the extreme of Candle 1
    - TP at 5% from entry
    """
    
    def __init__(self, config: dict):
        self.config = config
        self.active_signals: List[FVGSignal] = []
        self.completed_trades: List[TradeResult] = []
        self.candle_buffer: List[dict] = []
        self.min_candles = max(config.get("ema_trend_period", 200) + 10, 210)
        
        logger.info(f"Strategy engine initialized: {config.get('name', 'FVG V2')}")
        logger.info(f"  TP: {config['tp_pct']*100}% | Max SL: {config['max_sl_pct']*100}% | Min FVG: {config['min_fvg_pct']*100}%")
        logger.info(f"  Trend filter: {config.get('use_trend_filter', True)} (EMA{config.get('ema_trend_period', 200)})")
    
    def update_candles(self, df: pd.DataFrame) -> Optional[FVGSignal]:
        """
        Update with latest candle data and check for new FVG signals.
        
        Args:
            df: DataFrame with columns [timestamp, open, high, low, close, volume]
                Must have at least self.min_candles rows.
        
        Returns:
            FVGSignal if a new valid FVG is detected, None otherwise.
        """
        if len(df) < self.min_candles:
            logger.warning(f"Not enough candles: {len(df)} < {self.min_candles}")
            return None
        
        # Calculate indicators
        df = self._add_indicators(df)
        
        # Check for FVG on the last 3 candles
        signal = self._check_fvg(df)
        
        if signal:
            self.active_signals.append(signal)
            logger.info(f"🔍 NEW FVG DETECTED: {signal.direction} @ {signal.entry_price:.2f}")
            logger.info(f"   SL: {signal.stop_loss:.2f} ({signal.sl_pct*100:.2f}%) | TP: {signal.take_profit:.2f} ({signal.tp_pct*100:.2f}%)")
            logger.info(f"   FVG size: {signal.fvg_size_pct*100:.3f}% | Trend aligned: {signal.trend_aligned}")
        
        return signal
    
    def check_pending_fills(self, current_price: float, current_time: datetime) -> Optional[FVGSignal]:
        """
        Check if any pending signals should be activated (price reached entry).
        Called on every price update / new candle.
        
        Returns:
            Signal that was just filled, or None.
        """
        for signal in self.active_signals:
            if signal.status != "pending":
                continue
            
            # Check if entry was reached
            if signal.direction == "LONG" and current_price <= signal.entry_price:
                signal.status = "filled"
                signal.filled_at = current_price
                signal.filled_time = current_time
                logger.info(f"✅ ENTRY FILLED: {signal.direction} @ {current_price:.2f}")
                return signal
            
            elif signal.direction == "SHORT" and current_price >= signal.entry_price:
                signal.status = "filled"
                signal.filled_at = current_price
                signal.filled_time = current_time
                logger.info(f"✅ ENTRY FILLED: {signal.direction} @ {current_price:.2f}")
                return signal
            
            # Check expiry (12 candles = 48 hours for 4H)
            # We'll handle this in the bot loop based on candle count
        
        return None
    
    def check_exit_conditions(self, signal: FVGSignal, current_high: float, 
                              current_low: float, current_time: datetime) -> Optional[TradeResult]:
        """
        Check if a filled position should be closed (TP or SL hit).
        
        Returns:
            TradeResult if position should be closed, None otherwise.
        """
        if signal.status != "filled":
            return None
        
        if signal.direction == "LONG":
            # Check SL first (worst case assumption)
            if current_low <= signal.stop_loss:
                return self._close_trade(signal, signal.stop_loss, current_time, "SL")
            # Check TP
            elif current_high >= signal.take_profit:
                return self._close_trade(signal, signal.take_profit, current_time, "TP")
        
        elif signal.direction == "SHORT":
            if current_high >= signal.stop_loss:
                return self._close_trade(signal, signal.stop_loss, current_time, "SL")
            elif current_low <= signal.take_profit:
                return self._close_trade(signal, signal.take_profit, current_time, "TP")
        
        return None
    
    def cancel_expired_signals(self, current_candle_idx: int):
        """Cancel pending signals that have expired (price never reached entry)"""
        fill_lookback = self.config.get("fill_lookback_candles", 12)
        
        for signal in self.active_signals:
            if signal.status == "pending":
                if current_candle_idx - signal.candle_idx > fill_lookback:
                    signal.status = "expired"
                    logger.info(f"⏰ Signal expired: {signal.direction} @ {signal.entry_price:.2f}")
    
    def get_active_position(self) -> Optional[FVGSignal]:
        """Return the currently filled (active) position, if any"""
        for signal in self.active_signals:
            if signal.status == "filled":
                return signal
        return None
    
    def get_pending_signals(self) -> List[FVGSignal]:
        """Return all pending (unfilled) signals"""
        return [s for s in self.active_signals if s.status == "pending"]
    
    def get_stats(self) -> dict:
        """Return strategy performance stats"""
        if not self.completed_trades:
            return {"trades": 0}
        
        wins = [t for t in self.completed_trades if t.pnl_pct > 0]
        losses = [t for t in self.completed_trades if t.pnl_pct <= 0]
        
        total_pnl = sum(t.pnl_pct for t in self.completed_trades)
        
        return {
            "trades": len(self.completed_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(self.completed_trades) * 100,
            "total_pnl_pct": round(total_pnl * 100, 2),
            "avg_win": np.mean([t.pnl_pct * 100 for t in wins]) if wins else 0,
            "avg_loss": np.mean([t.pnl_pct * 100 for t in losses]) if losses else 0,
            "best_trade": max(t.pnl_pct * 100 for t in self.completed_trades),
            "worst_trade": min(t.pnl_pct * 100 for t in self.completed_trades),
            "pending_signals": len(self.get_pending_signals()),
            "active_position": self.get_active_position() is not None,
        }
    
    # ======================== PRIVATE METHODS ========================
    
    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add technical indicators to the dataframe"""
        df = df.copy()
        
        ema_period = self.config.get("ema_trend_period", 200)
        df["ema_trend"] = df["close"].ewm(span=ema_period, adjust=False).mean()
        
        # Volume SMA (for optional volume filter)
        df["vol_sma"] = df["volume"].rolling(20).mean()
        
        # RSI (for optional RSI filter)
        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1/14, min_periods=14).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14).mean()
        rs = avg_gain / avg_loss
        df["rsi"] = 100 - (100 / (1 + rs))
        
        return df
    
    def _check_fvg(self, df: pd.DataFrame) -> Optional[FVGSignal]:
        """Check the last 3 candles for a valid FVG"""
        cfg = self.config
        
        # Don't signal if we already have an active position
        if self.get_active_position() is not None:
            return None
        
        # Don't signal if we have pending signals
        if len(self.get_pending_signals()) > 0:
            return None
        
        i = len(df) - 1  # Current (3rd) candle
        if i < 2:
            return None
        
        c1 = df.iloc[i - 2]  # Candle 1
        c2 = df.iloc[i - 1]  # Candle 2 (impulse)
        c3 = df.iloc[i]      # Candle 3
        
        c2_body = c2["close"] - c2["open"]
        c2_range = c2["high"] - c2["low"]
        
        if c2_range == 0:
            return None
        
        body_ratio = abs(c2_body) / c2_range
        
        # ===== CHECK BULLISH FVG =====
        if c2_body > 0 and body_ratio >= cfg.get("impulse_body_ratio", 0.5):
            fvg_top = c3["low"]
            fvg_bottom = c1["high"]
            
            if fvg_top > fvg_bottom:
                fvg_size_pct = (fvg_top - fvg_bottom) / fvg_bottom
                
                if fvg_size_pct >= cfg.get("min_fvg_pct", 0.003):
                    entry_price = fvg_top
                    sl_price = c1["low"]
                    sl_pct = (entry_price - sl_price) / entry_price
                    
                    if 0 < sl_pct <= cfg.get("max_sl_pct", 0.04):
                        tp_price = entry_price * (1 + cfg.get("tp_pct", 0.05))
                        tp_pct = cfg.get("tp_pct", 0.05)
                        
                        # TREND FILTER
                        trend_aligned = True
                        if cfg.get("use_trend_filter", True):
                            ema_val = c3.get("ema_trend")
                            if pd.notna(ema_val) and c3["close"] < ema_val:
                                trend_aligned = False
                        
                        if not trend_aligned:
                            return None
                        
                        # VOLUME FILTER (optional)
                        if cfg.get("use_volume_filter", False):
                            vol_sma = c3.get("vol_sma")
                            if pd.notna(vol_sma) and vol_sma > 0:
                                if c2["volume"] < vol_sma * cfg.get("vol_threshold", 1.3):
                                    return None
                        
                        return FVGSignal(
                            signal_type="bullish",
                            direction="LONG",
                            timestamp=c3["timestamp"] if "timestamp" in df.columns else datetime.now(),
                            fvg_top=fvg_top,
                            fvg_bottom=fvg_bottom,
                            fvg_mid=(fvg_top + fvg_bottom) / 2,
                            entry_price=entry_price,
                            stop_loss=sl_price,
                            take_profit=tp_price,
                            sl_pct=sl_pct,
                            tp_pct=tp_pct,
                            fvg_size_pct=fvg_size_pct,
                            impulse_body_ratio=body_ratio,
                            trend_aligned=trend_aligned,
                            candle_idx=i,
                        )
        
        # ===== CHECK BEARISH FVG =====
        if c2_body < 0 and body_ratio >= cfg.get("impulse_body_ratio", 0.5):
            fvg_top = c1["low"]
            fvg_bottom = c3["high"]
            
            if fvg_top > fvg_bottom:
                fvg_size_pct = (fvg_top - fvg_bottom) / fvg_bottom
                
                if fvg_size_pct >= cfg.get("min_fvg_pct", 0.003):
                    entry_price = fvg_bottom
                    sl_price = c1["high"]
                    sl_pct = (sl_price - entry_price) / entry_price
                    
                    if 0 < sl_pct <= cfg.get("max_sl_pct", 0.04):
                        tp_price = entry_price * (1 - cfg.get("tp_pct", 0.05))
                        tp_pct = cfg.get("tp_pct", 0.05)
                        
                        trend_aligned = True
                        if cfg.get("use_trend_filter", True):
                            ema_val = c3.get("ema_trend")
                            if pd.notna(ema_val) and c3["close"] > ema_val:
                                trend_aligned = False
                        
                        if not trend_aligned:
                            return None
                        
                        if cfg.get("use_volume_filter", False):
                            vol_sma = c3.get("vol_sma")
                            if pd.notna(vol_sma) and vol_sma > 0:
                                if c2["volume"] < vol_sma * cfg.get("vol_threshold", 1.3):
                                    return None
                        
                        return FVGSignal(
                            signal_type="bearish",
                            direction="SHORT",
                            timestamp=c3["timestamp"] if "timestamp" in df.columns else datetime.now(),
                            fvg_top=fvg_top,
                            fvg_bottom=fvg_bottom,
                            fvg_mid=(fvg_top + fvg_bottom) / 2,
                            entry_price=entry_price,
                            stop_loss=sl_price,
                            take_profit=tp_price,
                            sl_pct=sl_pct,
                            tp_pct=tp_pct,
                            fvg_size_pct=fvg_size_pct,
                            impulse_body_ratio=body_ratio,
                            trend_aligned=trend_aligned,
                            candle_idx=i,
                        )
        
        return None
    
    def _close_trade(self, signal: FVGSignal, exit_price: float, 
                     exit_time: datetime, result: str) -> TradeResult:
        """Record a closed trade"""
        if signal.direction == "LONG":
            pnl_pct = (exit_price - signal.filled_at) / signal.filled_at
        else:
            pnl_pct = (signal.filled_at - exit_price) / signal.filled_at
        
        duration = (exit_time - signal.filled_time).total_seconds() / 60 if signal.filled_time else 0
        
        trade_result = TradeResult(
            signal=signal,
            exit_price=exit_price,
            exit_time=exit_time,
            pnl_pct=pnl_pct,
            pnl_usd=0,  # Will be calculated by the bot with position size
            result=result,
            duration_minutes=duration,
        )
        
        signal.status = "closed"
        self.completed_trades.append(trade_result)
        
        emoji = "🟢" if pnl_pct > 0 else "🔴"
        logger.info(f"{emoji} TRADE CLOSED: {signal.direction} | {result} | PnL: {pnl_pct*100:+.2f}% | Duration: {duration:.0f}min")
        
        return trade_result

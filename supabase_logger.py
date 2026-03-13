"""
===============================================================================
SUPABASE TRADE LOGGER
===============================================================================
Optional persistence layer for FVG Bot trades.
Reads SUPABASE_URL and SUPABASE_KEY from environment.
If either is missing, all methods are no-ops that return False.

SQL to create the required table in Supabase Dashboard:
-------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fvg_trades (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,

  -- Trade identification
  timestamp TIMESTAMPTZ NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
  symbol TEXT NOT NULL DEFAULT 'BTCUSDT',
  timeframe TEXT NOT NULL DEFAULT '4H',

  -- Prices
  entry_price NUMERIC NOT NULL,
  exit_price NUMERIC,
  stop_loss NUMERIC NOT NULL,
  take_profit NUMERIC NOT NULL,

  -- Sizing
  position_size_usdt NUMERIC NOT NULL,
  leverage INTEGER NOT NULL DEFAULT 3,

  -- Result
  result TEXT CHECK (result IN ('TP', 'SL', 'MANUAL', 'OPEN')),
  pnl_usdt NUMERIC,
  pnl_pct NUMERIC,
  rr_achieved NUMERIC,

  -- Quality metrics (most valuable for improving the bot)
  mae NUMERIC,   -- Maximum Adverse Excursion: how far it went against before going in favor (%)
  mfe NUMERIC,   -- Maximum Favorable Excursion: best unrealized gain at any point (%)
  duration_min INTEGER,

  -- Setup context
  fvg_size_pct NUMERIC,    -- FVG size as % of price
  sl_pct NUMERIC,          -- SL distance as % of price
  ema200_at_entry NUMERIC, -- EMA200 value at entry time
  price_vs_ema TEXT,       -- 'ABOVE' | 'BELOW'

  -- Temporal filters (critical for pattern analysis)
  killzone TEXT CHECK (killzone IN ('LONDON', 'NEW_YORK', 'ASIA', 'OFF_SESSION')),
  day_of_week TEXT CHECK (day_of_week IN ('MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN')),
  hour_utc INTEGER,

  -- Metadata
  is_paper BOOLEAN DEFAULT TRUE,
  bot_version TEXT DEFAULT 'v2.1',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for analysis queries
CREATE INDEX idx_fvg_trades_timestamp ON fvg_trades(timestamp DESC);
CREATE INDEX idx_fvg_trades_result ON fvg_trades(result);
CREATE INDEX idx_fvg_trades_killzone ON fvg_trades(killzone);
CREATE INDEX idx_fvg_trades_day ON fvg_trades(day_of_week);

-------------------------------------------------------------------------------
"""

import logging
import os
import time

logger = logging.getLogger("fvg_bot.supabase")


class SupabaseTradeLogger:
    """
    Optional Supabase persistence for FVG Bot trades.

    Reads SUPABASE_URL and SUPABASE_KEY from environment variables.
    If either is missing or supabase-py is not installed, all methods
    are no-ops that return False — the bot continues normally using CSV.

    Usage:
        logger = SupabaseTradeLogger()
        success = logger.log_trade(trade_data_dict)
        success = logger.update_mae_mfe(trade_id, mae, mfe)
    """

    MAX_RETRIES = 3
    RETRY_BACKOFF = [1, 2, 4]  # seconds between retries

    def __init__(self):
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_KEY", "")
        self.enabled = bool(url and key)
        self._client = None

        if self.enabled:
            try:
                from supabase import create_client  # type: ignore
                self._client = create_client(url, key)
                logger.info("✅ Supabase logger initialized")
            except ImportError:
                logger.warning(
                    "supabase-py not installed — Supabase logging disabled. "
                    "Run: pip install supabase"
                )
                self.enabled = False
            except Exception as e:
                logger.warning(f"Supabase init error: {e} — logging disabled")
                self.enabled = False

    def log_trade(self, trade_data: dict) -> bool:
        """
        Insert a closed trade record into fvg_trades.
        Returns True on success, False on failure (bot continues either way).
        """
        if not self.enabled:
            return False
        return self._with_retry(
            lambda: self._client.table("fvg_trades").insert(trade_data).execute()
        )

    def update_mae_mfe(self, trade_id: str, mae: float, mfe: float) -> bool:
        """
        Update MAE/MFE on an existing record by its UUID.
        Returns True on success, False on failure.
        """
        if not self.enabled:
            return False
        return self._with_retry(
            lambda: self._client.table("fvg_trades")
            .update({"mae": mae, "mfe": mfe})
            .eq("id", trade_id)
            .execute()
        )

    def _with_retry(self, fn) -> bool:
        for attempt, wait in enumerate(self.RETRY_BACKOFF):
            try:
                fn()
                return True
            except Exception as e:
                logger.warning(
                    f"Supabase error (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}"
                )
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(wait)
        logger.error(
            "Supabase: all retry attempts failed — trade NOT persisted to Supabase"
        )
        return False

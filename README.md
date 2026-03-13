# FVG Trading Bot v2.1

Automated futures bot for Bybit — Fair Value Gap (FVG) detection with EMA200 trend filter.

**Strategy:** V2 — FVG + Trend (EMA200) on BTC/USDT 4H  
**Backtest results:** +34.08% PnL | 30.8% Win Rate | 1.16x Profit Factor | 159 trades/year

## How it works

The bot scans BTC/USDT 4H candles every 4 hours looking for Fair Value Gaps — price gaps left by strong impulse candles that tend to get filled when price retraces. Trades are only taken in the direction of the EMA200 trend.

**Bullish FVG (Long):** Strong green candle creates a gap between candle 1's high and candle 3's low. Entry when price retraces to the gap. Only taken when price is above EMA200.

**Bearish FVG (Short):** Strong red candle creates a gap. Entry on retracement. Only when price is below EMA200.

## Features

- FVG detection with configurable parameters
- EMA200 trend filter (eliminated 43% of losing trades in backtest)
- Automatic SL/TP placement on Bybit (server-side — works if bot goes down)
- Risk management: 2% per trade, daily loss limits, kill switch
- Telegram notifications for signals, trades, and daily summaries
- CSV trade logging (primary) + optional Supabase persistence
- MAE/MFE tracking per trade (Maximum Adverse/Favorable Excursion)
- ICT killzone detection (London, New York, Asia)
- Supports Bybit Demo Trading, Testnet, and Live

## Requirements

- Python 3.11+
- Bybit account (Demo Trading recommended to start)
- Telegram bot (optional, for notifications)
- Supabase project (optional, for cloud persistence)

## Quick start

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/fvg-trading-bot.git
cd fvg-trading-bot

# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure via .env (recommended)
cp .env.example .env
# Edit .env with your API keys

# OR configure via config.json
cp config.example.json config.json
# Edit config.json with your keys

# Run
python bot.py

# Validate config without running
python bot.py --dry-run
```

## Configuration

### Option A — Environment variables (recommended for VPS/GitHub)

Copy `.env.example` to `.env` and fill in your values. Environment variables take priority over `config.json`.

```bash
BYBIT_API_KEY=your_api_key_here
BYBIT_API_SECRET=your_api_secret_here
BYBIT_DEMO=true
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Optional Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_service_role_key_here
```

### Option B — config.json

Copy `config.example.json` to `config.json` and fill in your values. **Never commit `config.json` to git.**

### Bybit API Keys

For **Demo Trading** (recommended to start):
1. Go to [bybit.com](https://bybit.com)
2. Enable Demo Trading (toggle in top right)
3. Create API key in Demo mode with Read-Write + Contract Trading permissions
4. Set `BYBIT_DEMO=true` in `.env`

For **Testnet**: Create keys at [testnet.bybit.com](https://testnet.bybit.com), set `BYBIT_DEMO=false` and `"testnet": true` in config.

For **Live**: Set both demo and testnet to false. Use with extreme caution.

### Telegram Notifications (optional)

1. Search **@BotFather** on Telegram → `/newbot` → get your **bot token**
2. Search **@userinfobot** → get your **chat ID**
3. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`

### Supabase (optional)

1. Create a free project at [supabase.com](https://supabase.com)
2. Run the SQL from `supabase_logger.py` (the `CREATE TABLE` block at the top) in the Supabase Dashboard SQL editor
3. Set `SUPABASE_URL` and `SUPABASE_KEY` (use the **service_role** key) in `.env`
4. If not configured, the bot works normally and logs only to CSV

### Strategy Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `tp_pct` | 0.05 | Take profit (5%) |
| `max_sl_pct` | 0.04 | Max stop loss (4%) |
| `min_fvg_pct` | 0.003 | Min FVG size (0.3%) |
| `impulse_body_ratio` | 0.5 | Min body/range ratio of impulse candle |
| `ema_trend_period` | 200 | EMA period for trend filter |
| `fill_lookback_candles` | 12 | Max candles to wait for entry fill (48h) |

## VPS Deployment (24/7 operation)

```bash
# On your VPS (Ubuntu)
bash setup_vps.sh

# Create .env with your credentials
nano /home/botuser/fvg_bot/.env

# Start
bash manage.sh start

# Monitor
bash manage.sh logs      # Live logs
bash manage.sh trades    # Recent trades
bash manage.sh stats     # Trade statistics
bash manage.sh status    # Is it running?
bash manage.sh stop      # Stop bot
bash manage.sh restart   # Restart bot
```

## Project Structure

```
fvg-trading-bot/
├── bot.py                  # Main orchestrator
├── strategy.py             # FVG detection & signal logic
├── exchange.py             # Bybit API connector
├── telegram_notifier.py    # Telegram alerts
├── supabase_logger.py      # Optional Supabase persistence (+ SQL schema)
├── config.example.json     # Config template
├── .env.example            # Environment variables template
├── requirements.txt        # Dependencies
├── setup_vps.sh            # VPS auto-setup script
├── manage.sh               # Bot management commands
└── logs/
    ├── bot.log             # Full bot log (rotating)
    └── trades.csv          # Trade history (CSV, primary)
```

## Trade CSV Fields (v2.1)

```
timestamp, direction, entry_price, exit_price, stop_loss, take_profit,
result, pnl_pct, pnl_usd, position_size, duration_min, fvg_size_pct, sl_pct,
mae, mfe, killzone, day_of_week, hour_utc, ema200_at_entry, price_vs_ema, bot_version
```

- **mae** — Maximum Adverse Excursion: how far price moved against the trade (%)
- **mfe** — Maximum Favorable Excursion: best unrealized gain at any point (%)
- **killzone** — ICT session: LONDON (02-05 UTC), NEW_YORK (07-10 UTC), ASIA (20-00 UTC)

## Risk Management

- **2% risk per trade** (configurable)
- **3x leverage** (configurable, max recommended 5x)
- **5% daily loss limit** → auto-pause
- **15% max drawdown** → auto-pause
- **20% kill switch** → close all positions, stop bot
- SL/TP set server-side on Bybit (protected even if bot crashes)

## Trade Frequency

Expect ~1 trade every 2-3 days on average. Long periods without trades are normal — selectivity is what makes the strategy profitable.

## Disclaimer

This bot is for educational and paper trading purposes. Trading futures with leverage carries significant risk of loss. Past backtest results do not guarantee future performance. Never trade with money you can't afford to lose.


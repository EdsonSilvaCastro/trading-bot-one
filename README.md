# FVG Trading Bot

Automated futures trading bot for Bybit using Fair Value Gap (FVG) detection with EMA200 trend filter.

**Strategy:** V2 — FVG + Trend (EMA200) on BTC/USDT 4H  
**Backtest results:** +34.08% PnL | 30.8% Win Rate | 1.16x Profit Factor | 159 trades/year

## How it works

The bot scans BTC/USDT 4H candles every 4 hours looking for Fair Value Gaps — price gaps left by strong impulse candles that tend to get "filled" when price retraces. It only takes trades aligned with the EMA200 trend direction.

**Bullish FVG (Long):** Strong green candle creates a gap between candle 1's high and candle 3's low. Entry when price retraces to the gap. Only taken when price is above EMA200.

**Bearish FVG (Short):** Strong red candle creates a gap. Entry on retracement. Only when price is below EMA200.

## Features

- FVG detection with configurable parameters
- EMA200 trend filter (eliminated 43% of losing trades in backtest)
- Automatic SL/TP placement on Bybit (server-side, works if bot goes down)
- Risk management: 2% per trade, daily loss limits, kill switch
- Telegram notifications for signals, trades, and daily summaries
- CSV trade logging for analysis
- Supports Bybit Demo Trading, Testnet, and Live

## Quick start

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/fvg-trading-bot.git
cd fvg-trading-bot

# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp config.example.json config.json
# Edit config.json with your Bybit API keys

# Run
python bot.py
```

## Configuration

Copy `config.example.json` to `config.json` and fill in:

### Bybit API Keys

For **Demo Trading** (recommended to start):
1. Go to [bybit.com](https://bybit.com)
2. Enable Demo Trading (toggle in top right)
3. Create API key in Demo mode with Read-Write + Contract Trading permissions
4. Set `"demo": true` in config

For **Testnet**: Create keys at [testnet.bybit.com](https://testnet.bybit.com), set `"testnet": true, "demo": false`

For **Live** (only after extensive paper trading): Set both to `false`. Use with caution.

### Telegram Notifications (optional)

1. Open Telegram, search **@BotFather**
2. Send `/newbot`, follow instructions → get your **bot token**
3. Search **@userinfobot** → get your **chat ID**
4. Update config:

```json
"notifications": {
    "enabled": true,
    "telegram_token": "123456:ABC-DEF...",
    "telegram_chat_id": "987654321"
}
```

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

The bot needs to run continuously. A $4-6/month VPS works perfectly.

```bash
# On your VPS (Ubuntu)
bash setup_vps.sh

# Configure
nano /home/botuser/fvg_bot/config.json

# Start
bash manage.sh start

# Monitor
bash manage.sh logs      # Live logs
bash manage.sh trades    # Recent trades
bash manage.sh status    # Running?
bash manage.sh stop      # Stop bot
```

## Project Structure

```
fvg-trading-bot/
├── bot.py                  # Main orchestrator
├── strategy.py             # FVG detection & signal logic
├── exchange.py             # Bybit API connector
├── telegram_notifier.py    # Telegram alerts
├── config.example.json     # Config template
├── requirements.txt        # Dependencies
├── setup_vps.sh            # VPS auto-setup script
├── manage.sh               # Bot management commands
└── logs/
    ├── bot.log             # Full bot log
    └── trades.csv          # Trade history
```

## Risk Management

- **2% risk per trade** (configurable)
- **3x leverage** (configurable, max recommended 5x)
- **5% daily loss limit** → auto-pause
- **15% max drawdown** → auto-pause
- **20% kill switch** → close all, stop bot
- SL/TP set server-side on Bybit (protected even if bot crashes)

## Trade Frequency

This is a selective strategy. Expect ~1 trade every 2-3 days on average. Long periods without trades are normal — that selectivity is what makes it profitable.

## Disclaimer

This bot is for educational and paper trading purposes. Trading futures with leverage carries significant risk of loss. Past backtest results do not guarantee future performance. Never trade with money you can't afford to lose.

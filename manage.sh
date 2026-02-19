#!/bin/bash
# ============================================
# FVG Bot — Management Commands
# ============================================

case "$1" in
    start)
        echo "Starting FVG Bot..."
        sudo systemctl start fvg-bot
        echo "✅ Bot started"
        ;;
    stop)
        echo "Stopping FVG Bot..."
        sudo systemctl stop fvg-bot
        echo "🛑 Bot stopped"
        ;;
    restart)
        echo "Restarting FVG Bot..."
        sudo systemctl restart fvg-bot
        echo "🔄 Bot restarted"
        ;;
    status)
        sudo systemctl status fvg-bot --no-pager
        ;;
    logs)
        sudo journalctl -u fvg-bot -f --no-pager
        ;;
    logs-today)
        sudo journalctl -u fvg-bot --since today --no-pager
        ;;
    trades)
        if [ -f logs/trades.csv ]; then
            echo "=== Recent Trades ==="
            tail -20 logs/trades.csv | column -t -s,
        else
            echo "No trades yet."
        fi
        ;;
    stats)
        echo "=== Bot Stats ==="
        echo "Uptime:"
        sudo systemctl show fvg-bot --property=ActiveEnterTimestamp --value
        echo ""
        echo "Memory usage:"
        ps aux | grep "[b]ot.py" | awk '{print $6/1024 " MB"}'
        echo ""
        if [ -f logs/trades.csv ]; then
            TOTAL=$(tail -n +2 logs/trades.csv | wc -l)
            WINS=$(tail -n +2 logs/trades.csv | awk -F, '{if ($7=="TP") count++} END {print count+0}')
            echo "Trades: $TOTAL | Wins: $WINS"
        fi
        ;;
    *)
        echo "FVG Bot Manager"
        echo ""
        echo "Usage: bash manage.sh [command]"
        echo ""
        echo "  start       Start the bot"
        echo "  stop        Stop the bot"
        echo "  restart     Restart the bot"
        echo "  status      Show bot status"
        echo "  logs        Show live logs (Ctrl+C to exit)"
        echo "  logs-today  Show today's logs"
        echo "  trades      Show recent trades"
        echo "  stats       Show bot statistics"
        ;;
esac

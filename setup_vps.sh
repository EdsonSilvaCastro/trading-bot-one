#!/bin/bash
# ============================================================================
# FVG BOT — VPS SETUP SCRIPT
# ============================================================================
# Este script configura todo en un VPS Linux (Ubuntu 22/24) desde cero.
# 
# CÓMO USAR:
#   1. Compra un VPS (ver instrucciones abajo)
#   2. Conéctate por SSH: ssh root@TU_IP
#   3. Sube este script: scp setup_vps.sh root@TU_IP:~/
#   4. Ejecuta: bash setup_vps.sh
# ============================================================================

set -e

echo "============================================"
echo "  FVG BOT — VPS SETUP"
echo "============================================"

# --- 1. System update ---
echo ">>> Actualizando sistema..."
apt update && apt upgrade -y

# --- 2. Install Python ---
echo ">>> Instalando Python 3.11+..."
apt install -y python3 python3-pip python3-venv git curl htop

# --- 3. Create bot user (no root for security) ---
echo ">>> Creando usuario 'botuser'..."
if ! id "botuser" &>/dev/null; then
    useradd -m -s /bin/bash botuser
    echo "  Usuario 'botuser' creado"
else
    echo "  Usuario 'botuser' ya existe"
fi

# --- 4. Setup bot directory ---
echo ">>> Configurando directorio del bot..."
BOT_DIR="/home/botuser/fvg_bot"
mkdir -p $BOT_DIR
mkdir -p $BOT_DIR/logs

# --- 5. Copy bot files ---
# (Asume que los archivos del bot están en /root/fvg_bot/)
if [ -d "/root/fvg_bot" ]; then
    cp /root/fvg_bot/*.py $BOT_DIR/
    cp /root/fvg_bot/*.json $BOT_DIR/
    cp /root/fvg_bot/requirements.txt $BOT_DIR/
    echo "  Archivos del bot copiados"
else
    echo "  ⚠ No se encontró /root/fvg_bot/"
    echo "  Sube los archivos manualmente a $BOT_DIR/"
fi

# --- 6. Python virtual environment ---
echo ">>> Creando entorno virtual..."
cd $BOT_DIR
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# --- 7. Set permissions ---
chown -R botuser:botuser $BOT_DIR

# --- 8. Create systemd service ---
echo ">>> Creando servicio systemd..."
cat > /etc/systemd/system/fvg-bot.service << 'EOF'
[Unit]
Description=FVG Trading Bot — V2 FVG + Trend
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/home/botuser/fvg_bot
ExecStart=/home/botuser/fvg_bot/venv/bin/python bot.py
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

# Safety: restart if it crashes, but not too aggressively
StartLimitIntervalSec=300
StartLimitBurst=5

# Environment
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# --- 9. Create management script ---
echo ">>> Creando script de management..."
cat > $BOT_DIR/manage.sh << 'MGMT'
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
        # Show live logs
        sudo journalctl -u fvg-bot -f --no-pager
        ;;
    logs-today)
        sudo journalctl -u fvg-bot --since today --no-pager
        ;;
    trades)
        # Show recent trades
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
    update)
        echo "Stopping bot for update..."
        sudo systemctl stop fvg-bot
        echo "Activate venv and update manually, then run: bash manage.sh start"
        ;;
    *)
        echo "FVG Bot Manager"
        echo ""
        echo "Usage: bash manage.sh [command]"
        echo ""
        echo "Commands:"
        echo "  start       Start the bot"
        echo "  stop        Stop the bot"
        echo "  restart     Restart the bot"
        echo "  status      Show bot status"
        echo "  logs        Show live logs (Ctrl+C to exit)"
        echo "  logs-today  Show today's logs"
        echo "  trades      Show recent trades"
        echo "  stats       Show bot statistics"
        echo "  update      Stop bot for manual update"
        ;;
esac
MGMT

chmod +x $BOT_DIR/manage.sh
chown botuser:botuser $BOT_DIR/manage.sh

# --- 10. Setup log rotation ---
echo ">>> Configurando rotación de logs..."
cat > /etc/logrotate.d/fvg-bot << 'LOGR'
/home/botuser/fvg_bot/logs/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 0640 botuser botuser
}
LOGR

# --- 11. Basic firewall ---
echo ">>> Configurando firewall..."
apt install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw --force enable

# --- 12. Setup automatic security updates ---
echo ">>> Configurando updates automáticos..."
apt install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades 2>/dev/null || true

echo ""
echo "============================================"
echo "  ✅ SETUP COMPLETO"
echo "============================================"
echo ""
echo "  Próximos pasos:"
echo ""
echo "  1. Edita config.json con tus API keys:"
echo "     nano $BOT_DIR/config.json"
echo ""
echo "  2. Verifica la configuración:"
echo "     cd $BOT_DIR && source venv/bin/activate"
echo "     python bot.py --dry-run"
echo ""
echo "  3. Inicia el bot:"
echo "     bash manage.sh start"
echo ""
echo "  4. Ve los logs en vivo:"
echo "     bash manage.sh logs"
echo ""
echo "  El bot se reinicia automáticamente si se cae."
echo "  Se reinicia automáticamente si el VPS se reinicia."
echo ""
echo "============================================"

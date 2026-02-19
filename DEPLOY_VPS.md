# Guía de Despliegue en VPS — FVG Bot

## Paso 1: Comprar un VPS

Necesitas el VPS más barato que exista. El bot usa menos de 100MB de RAM y casi nada de CPU.

### Opción A: DigitalOcean (recomendado para principiantes)

1. Ve a **https://digitalocean.com** y crea cuenta
2. Crea un **Droplet**:
   - Región: **New York** o **San Francisco** (cerca de los servidores de Bybit)
   - OS: **Ubuntu 24.04 LTS**
   - Plan: **Basic → Regular → $4/mes** (512MB RAM, 10GB SSD)
   - Autenticación: **SSH Key** (más seguro) o Password
3. Toma nota de la **IP** del droplet

### Opción B: Hetzner (más barato, servidores en Europa)

1. Ve a **https://hetzner.com/cloud**
2. Crea servidor:
   - Location: **Ashburn** o **Hillsboro** (USA)
   - OS: **Ubuntu 24.04**
   - Type: **CX22** (~€4.5/mes)

### Opción C: Vultr

1. Ve a **https://vultr.com**
2. Deploy server: **Cloud Compute → Regular → $5/mes**
3. OS: **Ubuntu 24.04**

---

## Paso 2: Conectarte al VPS

### Desde Mac/Linux (Terminal)

```bash
ssh root@TU_IP_DEL_VPS
```

### Desde Windows

Descarga **PuTTY** (https://putty.org) o usa **Windows Terminal**:
```bash
ssh root@TU_IP_DEL_VPS
```

Te pedirá la contraseña que configuraste al crear el VPS.

---

## Paso 3: Subir los archivos del bot

Desde tu computadora local, abre otra terminal y ejecuta:

```bash
# Descomprime el bot primero si no lo has hecho
tar -xzf fvg_bot.tar.gz

# Sube la carpeta al VPS
scp -r fvg_bot root@TU_IP_DEL_VPS:~/
```

---

## Paso 4: Ejecutar el setup automático

De vuelta en la terminal SSH del VPS:

```bash
cd ~/fvg_bot
bash setup_vps.sh
```

Esto instala todo automáticamente: Python, dependencias, firewall, y crea un servicio que mantiene el bot corriendo 24/7.

---

## Paso 5: Configurar las API keys

```bash
cd /home/botuser/fvg_bot
nano config.json
```

Cambia estas dos líneas con tus keys de **Bybit testnet**:
```json
"api_key": "TU_API_KEY_AQUI",
"api_secret": "TU_API_SECRET_AQUI"
```

Guarda: `Ctrl+O` → `Enter` → `Ctrl+X`

---

## Paso 6: Verificar y arrancar

```bash
cd /home/botuser/fvg_bot

# Verificar que todo esté bien
source venv/bin/activate
python bot.py --dry-run
deactivate

# Arrancar el bot
bash manage.sh start

# Ver los logs en vivo
bash manage.sh logs
```

Deberías ver algo como:
```
14:00:05 | ============================================================
14:00:05 |   FVG BOT — V2: FVG + Trend (EMA200)
14:00:05 |   TESTNET
14:00:05 | ============================================================
14:00:05 | Connected to Bybit TESTNET
14:00:05 |   ✅ Connection verified
14:00:06 |   Balance: 10000.00 USDT
14:00:06 | 🚀 Bot starting...
```

Presiona `Ctrl+C` para salir de los logs (el bot sigue corriendo).

---

## Comandos del día a día

Todos desde `/home/botuser/fvg_bot/`:

| Comando | Qué hace |
|---------|----------|
| `bash manage.sh start` | Inicia el bot |
| `bash manage.sh stop` | Detiene el bot |
| `bash manage.sh restart` | Reinicia el bot |
| `bash manage.sh status` | Muestra si está corriendo |
| `bash manage.sh logs` | Logs en vivo (Ctrl+C para salir) |
| `bash manage.sh logs-today` | Logs de hoy |
| `bash manage.sh trades` | Últimos trades |
| `bash manage.sh stats` | Estadísticas |

---

## ¿Qué pasa si...?

**El bot se cae:** Se reinicia solo en 30 segundos (systemd lo maneja).

**El VPS se reinicia:** El bot arranca automáticamente.

**Quiero actualizar el código:** 
```bash
bash manage.sh stop
# Edita los archivos
bash manage.sh start
```

**Quiero ver los trades en mi computadora:**
```bash
# Desde tu computadora local
scp root@TU_IP:/home/botuser/fvg_bot/logs/trades.csv ~/Desktop/
```

**Quiero cambiar parámetros:**
```bash
bash manage.sh stop
nano config.json
bash manage.sh start
```

---

## Monitoreo remoto (opcional)

Si quieres recibir notificaciones en tu teléfono cuando el bot abre/cierra trades, puedes configurar Telegram:

1. Busca **@BotFather** en Telegram
2. Crea un bot: `/newbot` → te dará un token
3. Busca tu chat ID con **@userinfobot**
4. Edita config.json:
```json
"notifications": {
    "enabled": true,
    "telegram_token": "TU_TOKEN",
    "telegram_chat_id": "TU_CHAT_ID"
}
```

(La funcionalidad de Telegram se puede agregar como siguiente paso)

---

## Costo total

| Concepto | Costo |
|----------|-------|
| VPS | $4-6 USD/mes |
| Bybit testnet | Gratis |
| Bot | Gratis (ya lo tienes) |
| **Total** | **~$5 USD/mes** |

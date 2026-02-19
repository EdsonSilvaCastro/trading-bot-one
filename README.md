# FVG Trading Bot — V2: FVG + Trend (EMA200)
## Paper Trading en Bybit Testnet

---

## Estructura del proyecto

```
fvg_bot/
├── bot.py          # Orquestador principal — corre este archivo
├── strategy.py     # Motor de detección de FVG y señales
├── exchange.py     # Conector con Bybit API (V5)
├── config.json     # Configuración (API keys, parámetros)
├── requirements.txt
└── logs/
    ├── bot.log     # Log completo del bot
    └── trades.csv  # Historial de trades en CSV
```

---

## Setup paso a paso

### 1. Crear cuenta testnet en Bybit

1. Ve a **https://testnet.bybit.com**
2. Regístrate con email (es gratis, no necesitas KYC)
3. Una vez dentro, ve a **API Management** (esquina superior derecha → API)
4. Crea un nuevo API key:
   - Nombre: `fvg_bot`
   - Permisos: **Read-Write** (necesita leer datos y colocar órdenes)
   - IP restrictions: puedes dejarlo abierto para testnet
5. Guarda el **API Key** y **API Secret** — los necesitarás

### 2. Obtener fondos de testnet

En Bybit testnet, puedes obtener fondos ficticios:
1. Ve a **Assets** → **Faucet** o busca "testnet faucet bybit"
2. Solicita USDT de prueba (te darán entre 1,000 y 10,000 USDT)
3. Transfiere a tu cuenta **Unified Trading Account** si es necesario

### 3. Instalar dependencias

```bash
# Crear entorno virtual (recomendado)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Instalar paquetes
pip install -r requirements.txt
```

### 4. Configurar el bot

Edita `config.json` y reemplaza las API keys:

```json
{
  "exchange": {
    "testnet": true,
    "api_key": "TU_API_KEY_AQUI",
    "api_secret": "TU_API_SECRET_AQUI"
  }
}
```

**IMPORTANTE**: `"testnet": true` asegura que el bot se conecte a testnet.
Nunca pongas `false` hasta que estés 100% seguro de lo que haces.

### 5. Verificar configuración

```bash
python bot.py --dry-run
```

Esto imprime la configuración sin ejecutar nada. Verifica que todo se vea bien.

### 6. Ejecutar el bot

```bash
python bot.py
```

El bot:
1. Se conecta a Bybit testnet
2. Verifica balance
3. Configura leverage (3x) y margin mode (isolated)
4. Cada 4 horas: descarga las últimas 250 velas, calcula EMA200, busca FVGs
5. Si detecta un FVG válido alineado con la tendencia: coloca una orden limit
6. Si la orden se llena: el SL y TP están ya configurados en Bybit
7. Cada 5 minutos: revisa el estado de órdenes y posiciones

Para detener el bot: **Ctrl+C** (hace un shutdown graceful)

---

## Cómo funciona la estrategia

### Detección de FVG (Fair Value Gap)

El bot analiza las últimas 3 velas:

**Bullish FVG (Long):**
- Vela 2 es una vela alcista fuerte (>50% cuerpo)
- Existe un gap entre el HIGH de Vela 1 y el LOW de Vela 3
- El gap es > 0.3% del precio

**Bearish FVG (Short):**
- Vela 2 es una vela bajista fuerte (>50% cuerpo)
- Existe un gap entre el LOW de Vela 1 y el HIGH de Vela 3

### Filtro de tendencia (EMA200)

- Solo toma LONGS si el precio está **arriba** de la EMA200
- Solo toma SHORTS si el precio está **abajo** de la EMA200
- Este filtro redujo los trades de 279 a 159 y duplicó el PnL en backtest

### Entry, SL, TP

- **Entry**: Orden limit al inicio del FVG (parte superior para longs, inferior para shorts)
- **Stop Loss**: En el extremo de la Vela 1 (máximo 4% del precio)
- **Take Profit**: 5% desde el entry
- **Expiry**: Si la entrada no se llena en 12 velas (48 horas), se cancela

### Gestión de riesgo

- **Position size**: 2% del balance por trade (configurable)
- **Leverage**: 3x (configurable, recomendado no exceder 5x)
- **Margin**: Isolated (limita la pérdida al margen asignado)
- **Max daily loss**: 5% del balance inicial → pausa hasta el día siguiente
- **Max drawdown**: 15% → pausa el bot
- **Kill switch**: 20% → cierra todo y se detiene

---

## Parámetros configurables

| Parámetro | Default | Descripción |
|-----------|---------|-------------|
| `tp_pct` | 0.05 | Take profit (5%) |
| `max_sl_pct` | 0.04 | Máximo stop loss permitido (4%) |
| `min_fvg_pct` | 0.003 | Tamaño mínimo del FVG (0.3%) |
| `impulse_body_ratio` | 0.5 | Mínimo ratio cuerpo/rango de la vela impulso |
| `leverage` | 3 | Apalancamiento |
| `position_size_pct` | 0.02 | % del balance por trade |
| `fill_lookback_candles` | 12 | Velas máximas para esperar el fill (48h en 4H) |

---

## Logs y monitoreo

### bot.log
Log completo con timestamps. Ejemplo:
```
14:00:05 | 📊 Candle analysis at 2025-02-15 14:00
14:00:05 |    Latest candle: 2025-02-15 12:00 | Close: 97542.00
14:00:05 |    Balance: 10000.00 USDT | PnL: 0.00
14:00:06 | 🔍 NEW FVG DETECTED: LONG @ 96800.00
14:00:06 |    SL: 95200.00 (1.65%) | TP: 101640.00 (5.00%)
14:00:06 |    FVG size: 0.45% | Trend aligned: True
14:00:06 |    📝 Order placed: Buy 0.006 BTCUSDT @ 96800.00
```

### trades.csv
Historial de trades que puedes abrir en Excel o Google Sheets:
```csv
timestamp,direction,entry_price,exit_price,stop_loss,take_profit,result,pnl_pct,...
```

---

## Solución de problemas

**"Connection error"**: Verifica tu conexión a internet y que las API keys sean correctas.

**"Not enough candle data"**: Normal al inicio. El bot necesita 200+ velas históricas.

**"Position size below minimum"**: Tu balance es muy bajo. Necesitas al menos ~$50 USDT para operar BTC con los parámetros default.

**"Daily loss limit reached"**: El bot se pausó porque perdiste >5% en un día. Se reanuda al siguiente día o reinicia manualmente.

**No genera señales**: Es normal. En 4H, la estrategia V2 genera ~159 trades/año, es decir aproximadamente 1 trade cada 2-3 días. Paciencia.

---

## Siguiente paso: datos reales y live trading

Cuando estés satisfecho con el paper trading:

1. Corre al menos 2-4 semanas en testnet
2. Revisa el trades.csv y compara con el backtest
3. Si los resultados son consistentes, cambia `"testnet": false` en config.json
4. Usa API keys de tu cuenta real de Bybit
5. **Empieza con el monto mínimo posible**
6. Monitorea los primeros 10-20 trades de cerca

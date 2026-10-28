"""
Klejsi Gold Signals — signal-only educational prototype.
Uses Twelve Data XAU/USD candles; never places trades.
Signals are not guaranteed and the strategy has not been backtested.
"""
import os
import requests
from datetime import datetime, timezone

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()
TEST_TELEGRAM_DELIVERY = os.getenv("TEST_TELEGRAM_DELIVERY", "false").lower() == "true"
SESSION = requests.Session()
BASE_URL = "https://api.twelvedata.com/time_series"


def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Missing Telegram secrets: check repository Actions secrets.")
    response = SESSION.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError("Telegram API rejected the message; check TELEGRAM_CHAT_ID and bot access.")


def get_bars(interval, outputsize=120):
    if not TWELVE_DATA_API_KEY:
        raise RuntimeError("Missing TWELVE_DATA_API_KEY repository secret.")
    response = SESSION.get(
        BASE_URL,
        params={
            "symbol": "XAU/USD",
            "interval": interval,
            "outputsize": outputsize,
            "apikey": TWELVE_DATA_API_KEY,
            "format": "JSON",
            "order": "desc",
            "timezone": "UTC",
        },
        timeout=25,
    )
    response.raise_for_status()
    data = response.json()
    if "values" not in data:
        message = data.get("message") or data.get("code") or "no candle data returned"
        raise RuntimeError(f"Twelve Data error for {interval}: {message}")
    bars = list(reversed(data["values"]))
    parsed = []
    for item in bars:
        try:
            parsed.append({
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
                "datetime": item.get("datetime", ""),
            })
        except (KeyError, TypeError, ValueError):
            continue
    # Conservatively ignore the newest candle because it may still be forming.
    if len(parsed) < 60:
        raise RuntimeError(f"Not enough valid {interval} candles ({len(parsed)}).")
    return parsed[:-1]


def ema(values, period):
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1)
    value = sum(values[:period]) / period
    for price in values[period:]:
        value = alpha * price + (1.0 - alpha) * value
    return value


def atr(bars, period=14):
    if len(bars) < period + 1:
        return None
    true_ranges = []
    for i in range(1, len(bars)):
        current, previous = bars[i], bars[i - 1]
        true_ranges.append(max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"]),
        ))
    recent = true_ranges[-period:]
    return sum(recent) / len(recent)


def make_signal():
    # Three independent timeframe requests: higher-timeframe bias, setup, trigger.
    h1 = get_bars("1h")
    m15 = get_bars("15min")
    m5 = get_bars("5min")

    h1_closes = [b["close"] for b in h1]
    ema20, ema50 = ema(h1_closes, 20), ema(h1_closes, 50)
    if ema20 is None or ema50 is None:
        return None

    # Evaluate a completed 15m candle against the six candles before it.
    setup = m15[-1]
    prior15 = m15[-7:-1]
    prior_high = max(b["high"] for b in prior15)
    prior_low = min(b["low"] for b in prior15)
    bullish_sweep = setup["low"] < prior_low and setup["close"] > prior_low and setup["close"] > setup["open"]
    bearish_sweep = setup["high"] > prior_high and setup["close"] < prior_high and setup["close"] < setup["open"]

    # Require a completed 5m candle to break the range of the three candles before it.
    trigger = m5[-1]
    prior5 = m5[-4:-1]
    recent_atr = atr(m5)
    if recent_atr is None or recent_atr <= 0:
        return None
    body = abs(trigger["close"] - trigger["open"])
    if body < 0.20 * recent_atr:
        return None
    break_high = max(b["high"] for b in prior5)
    break_low = min(b["low"] for b in prior5)
    bullish_break = trigger["close"] > break_high and trigger["close"] > trigger["open"]
    bearish_break = trigger["close"] < break_low and trigger["close"] < trigger["open"]

    direction = None
    if ema20 > ema50 and bullish_sweep and bullish_break:
        direction = "BUY"
    elif ema20 < ema50 and bearish_sweep and bearish_break:
        direction = "SELL"
    if direction is None:
        return None

    entry = trigger["close"]  # reference price only; broker price/spread can differ
    if direction == "BUY":
        sl = min(b["low"] for b in m5[-6:])
        risk = entry - sl
        if risk <= 0:
            return None
        tp1, tp2 = entry + 1.5 * risk, entry + 2.0 * risk
    else:
        sl = max(b["high"] for b in m5[-6:])
        risk = sl - entry
        if risk <= 0:
            return None
        tp1, tp2 = entry - 1.5 * risk, entry - 2.0 * risk

    candle_time = trigger["datetime"] or "time unavailable"
    checked = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"📊 XAU/USD — {direction} SETUP (TEST MODE)\n"
        f"Entry reference: {entry:.2f}\n"
        f"Stop Loss: {sl:.2f}\n"
        f"TP1 (1.5R): {tp1:.2f}\n"
        f"TP2 (2R): {tp2:.2f}\n"
        f"Trigger candle (UTC): {candle_time}\n"
        f"Detected: {checked}\n\n"
        "Signal only — no trade is placed. Verify the price on your MT5 broker, "
        "spread, news and risk before considering any trade. Strategy is unbacktested "
        "and may produce false signals; no accuracy or profit is guaranteed."
    )


def main():
    print("Starting one XAU/USD market check.")
    if TEST_TELEGRAM_DELIVERY:
        telegram_send("✅ Telegram test successful: Klejsi Gold Signals bot can send messages.")
    signal = make_signal()
    if signal:
        print(signal)
        telegram_send(signal)
        print("Signal sent to Telegram.")
    else:
        print("No signal setup on this check; no trade signal sent.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Show a clear failure in GitHub Actions logs without sending repeated error messages to Telegram.
        print(f"BOT ERROR: {type(exc).__name__}: {exc}")
        raise

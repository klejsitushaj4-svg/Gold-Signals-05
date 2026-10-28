"""
Gold Signals Telegram Bot — prototype (signal-only).
Educational prototype; not a validated or backtested strategy.
It does not execute trades or calculate lot sizes.
"""
import os
import requests
from datetime import datetime, timezone

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()
TEST_TELEGRAM_DELIVERY = os.getenv("TEST_TELEGRAM_DELIVERY", "false").lower() == "true"


def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID secret.")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API rejected the message: {result}")


def get_bars(interval, outputsize=100):
    if not TWELVE_DATA_API_KEY:
        raise RuntimeError("Missing TWELVE_DATA_API_KEY secret.")
    response = requests.get(
        "https://api.twelvedata.com/time_series",
        params={
            "symbol": "XAU/USD",
            "interval": interval,
            "outputsize": outputsize,
            "apikey": TWELVE_DATA_API_KEY,
            "format": "JSON",
        },
        timeout=25,
    )
    response.raise_for_status()
    data = response.json()
    if "values" not in data:
        raise RuntimeError(f"Market data unavailable: {data}")
    values = list(reversed(data["values"]))
    return [
        {
            "open": float(x["open"]),
            "high": float(x["high"]),
            "low": float(x["low"]),
            "close": float(x["close"]),
            "datetime": x.get("datetime", ""),
        }
        for x in values
    ]


def ema(values, period):
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def make_signal():
    h1 = get_bars("1h", 100)
    m15 = get_bars("15min", 100)
    m5 = get_bars("5min", 100)

    closes_h1 = [bar["close"] for bar in h1]
    fast = ema(closes_h1, 20)
    slow = ema(closes_h1, 50)
    if fast is None or slow is None:
        return None

    recent = m15[-8:-1]
    current = m15[-1]
    recent_high = max(bar["high"] for bar in recent)
    recent_low = min(bar["low"] for bar in recent)
    bullish_sweep = current["low"] < recent_low and current["close"] > recent_low
    bearish_sweep = current["high"] > recent_high and current["close"] < recent_high

    last5 = m5[-1]
    prev5 = m5[-2]
    bullish_break = last5["close"] > prev5["high"]
    bearish_break = last5["close"] < prev5["low"]

    direction = None
    if fast > slow and bullish_sweep and bullish_break:
        direction = "BUY"
    elif fast < slow and bearish_sweep and bearish_break:
        direction = "SELL"
    if not direction:
        return None

    entry = last5["close"]
    if direction == "BUY":
        sl = min(bar["low"] for bar in m5[-6:])
        risk = entry - sl
        if risk <= 0:
            return None
        tp1, tp2 = entry + 1.5 * risk, entry + 2 * risk
    else:
        sl = max(bar["high"] for bar in m5[-6:])
        risk = sl - entry
        if risk <= 0:
            return None
        tp1, tp2 = entry - 1.5 * risk, entry - 2 * risk

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"⚠️ GOLD {direction} — PROTOTYPE SIGNAL\n"
        f"Entry reference: {entry:.2f}\n"
        f"Stop Loss: {sl:.2f}\n"
        f"TP1 (1.5R): {tp1:.2f}\n"
        f"TP2 (2R): {tp2:.2f}\n"
        f"Time: {now}\n\n"
        "Educational prototype only. Verify broker price, spread, and news. "
        "Not backtested; no guarantee of accuracy. This bot does not calculate position size."
    )


def main():
    print("Starting one market check.")
    if TEST_TELEGRAM_DELIVERY:
        telegram_send("✅ Telegram test successful: Klejsi Gold Signals bot can send messages.")

    signal = make_signal()
    if signal:
        print(signal)
        telegram_send(signal)
        print("Signal sent to Telegram.")
    else:
        print("No signal conditions met on this check; no signal message sent.")


if __name__ == "__main__":
    main()

"""
Klejsi Gold Signals — educational signal-only prototype.
Strategies: scalping, swing, and high-volatility/news-reaction setup.
Does not place trades. No economic calendar is connected, so volatility signals
are NOT confirmation that a scheduled news event occurred. Not backtested.
"""
import os
import json
import base64
import requests
from datetime import datetime, timezone

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()
TEST_TELEGRAM_DELIVERY = os.getenv("TEST_TELEGRAM_DELIVERY", "false").lower() == "true"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "").strip()
GITHUB_REF_NAME = os.getenv("GITHUB_REF_NAME", "main").strip() or "main"
STATE_PATH = "signals_state.json"
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
    if not response.json().get("ok"):
        raise RuntimeError("Telegram API rejected the message; check bot access and chat ID.")


def get_bars(interval, outputsize=120):
    if not TWELVE_DATA_API_KEY:
        raise RuntimeError("Missing TWELVE_DATA_API_KEY repository secret.")
    response = SESSION.get(
        BASE_URL,
        params={
            "symbol": "XAU/USD", "interval": interval, "outputsize": outputsize,
            "apikey": TWELVE_DATA_API_KEY, "format": "JSON", "order": "desc",
            "timezone": "UTC",
        },
        timeout=25,
    )
    response.raise_for_status()
    data = response.json()
    if "values" not in data:
        message = data.get("message") or data.get("code") or "no candle data returned"
        raise RuntimeError(f"Twelve Data error for {interval}: {message}")
    parsed = []
    for item in reversed(data["values"]):
        try:
            parsed.append({
                "open": float(item["open"]), "high": float(item["high"]),
                "low": float(item["low"]), "close": float(item["close"]),
                "datetime": item.get("datetime", ""),
            })
        except (KeyError, TypeError, ValueError):
            continue
    # Ignore the newest candle because it may still be forming.
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
    ranges = []
    for i in range(1, len(bars)):
        cur, prev = bars[i], bars[i - 1]
        ranges.append(max(cur["high"] - cur["low"],
                          abs(cur["high"] - prev["close"]),
                          abs(cur["low"] - prev["close"])))
    return sum(ranges[-period:]) / period


def make_trade_message(label, direction, bars, lookback=6, extra_note=""):
    trigger = bars[-1]
    recent = bars[-lookback:]
    entry = trigger["close"]
    if direction == "BUY":
        sl = min(b["low"] for b in recent)
        risk = entry - sl
        if risk <= 0:
            return None
        tp1, tp2 = entry + 1.5 * risk, entry + 2.0 * risk
    else:
        sl = max(b["high"] for b in recent)
        risk = sl - entry
        if risk <= 0:
            return None
        tp1, tp2 = entry - 1.5 * risk, entry - 2.0 * risk
    checked = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    note = f"\n{extra_note}" if extra_note else ""
    return (
        f"📊 XAU/USD — {label}: {direction}\n"
        f"Entry reference: {entry:.2f}\nStop Loss: {sl:.2f}\n"
        f"TP1 (1.5R): {tp1:.2f}\nTP2 (2R): {tp2:.2f}\n"
        f"Completed candle (UTC): {trigger['datetime'] or 'unavailable'}\n"
        f"Detected: {checked}{note}\n\n"
        "Signal only; no trade is placed. Check your MT5 broker price, spread, "
        "slippage and risk. This strategy is not backtested; no profit or accuracy is guaranteed."
    )


def breakout_direction(bars, lookback=3):
    trigger = bars[-1]
    prior = bars[-lookback-1:-1]
    if trigger["close"] > max(b["high"] for b in prior) and trigger["close"] > trigger["open"]:
        return "BUY"
    if trigger["close"] < min(b["low"] for b in prior) and trigger["close"] < trigger["open"]:
        return "SELL"
    return None


def generate_signals():
    # Four requests per check: M5 scalping/news reaction, M15 confirmation,
    # H1 trend, H4 swing trend. Check API quota for your Twelve Data plan.
    m5 = get_bars("5min")
    m15 = get_bars("15min")
    h1 = get_bars("1h")
    h4 = get_bars("4h")
    signals = []

    # 1) SCALPING: H1 trend + M15 alignment + completed M5 breakout.
    h1e20 = ema([b["close"] for b in h1], 20)
    h1e50 = ema([b["close"] for b in h1], 50)
    m15e20 = ema([b["close"] for b in m15], 20)
    m15e50 = ema([b["close"] for b in m15], 50)
    m5atr = atr(m5)
    if all(x is not None for x in (h1e20, h1e50, m15e20, m15e50, m5atr)) and m5atr > 0:
        d = breakout_direction(m5, 3)
        body = abs(m5[-1]["close"] - m5[-1]["open"])
        if body >= 0.20 * m5atr:
            if d == "BUY" and h1e20 > h1e50 and m15e20 > m15e50:
                msg = make_trade_message("SCALPING (M5)", d, m5, 6)
                if msg: signals.append(msg)
            elif d == "SELL" and h1e20 < h1e50 and m15e20 < m15e50:
                msg = make_trade_message("SCALPING (M5)", d, m5, 6)
                if msg: signals.append(msg)

    # 2) SWING: H4 direction + H1 breakout. Wider stop uses H1 structure.
    h4e20 = ema([b["close"] for b in h4], 20)
    h4e50 = ema([b["close"] for b in h4], 50)
    h1_direction = breakout_direction(h1, 6)
    if h4e20 is not None and h4e50 is not None:
        if h1_direction == "BUY" and h4e20 > h4e50:
            msg = make_trade_message("SWING (H1/H4)", "BUY", h1, 6)
            if msg: signals.append(msg)
        elif h1_direction == "SELL" and h4e20 < h4e50:
            msg = make_trade_message("SWING (H1/H4)", "SELL", h1, 6)
            if msg: signals.append(msg)

    # 3) NEWS/volatility reaction: detects an unusually large completed M5 candle.
    # This is NOT tied to a live economic calendar and may be caused by other factors.
    if m5atr is not None and m5atr > 0:
        candle = m5[-1]
        candle_range = candle["high"] - candle["low"]
        body = abs(candle["close"] - candle["open"])
        direction = "BUY" if candle["close"] > candle["open"] else (
            "SELL" if candle["close"] < candle["open"] else None
        )
        breakout = breakout_direction(m5, 3)
        if (direction and direction == breakout and candle_range >= 2.0 * m5atr
                and body >= 0.65 * candle_range):
            msg = make_trade_message(
                "NEWS/VOLATILITY REACTION (not calendar-confirmed)", direction, m5, 5,
                "⚠️ Volatility spike only: no economic calendar is connected, so this is NOT confirmation of a news event. Avoid chasing fast candles; spreads/slippage may be extreme."
            )
            if msg: signals.append(msg)

    return signals



def github_headers():
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        raise RuntimeError("Persistent duplicate protection unavailable: GitHub token/repository environment missing.")
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def load_signal_state():
    """Load previously sent signal IDs from the repository so scheduled runs deduplicate."""
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/contents/{STATE_PATH}"
    response = SESSION.get(
        url, headers=github_headers(), params={"ref": GITHUB_REF_NAME}, timeout=20
    )
    if response.status_code == 404:
        return set(), None
    response.raise_for_status()
    payload = response.json()
    raw = base64.b64decode(payload.get("content", "")).decode("utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {"sent": []}
    return set(data.get("sent", [])), payload.get("sha")


def save_signal_state(signal_ids, existing_sha):
    """Persist the most recent signal IDs in GitHub; Actions runners are temporary."""
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/contents/{STATE_PATH}"
    data = {"sent": list(signal_ids)[-200:]}
    payload = {
        "message": "Update sent-signal deduplication state",
        "content": base64.b64encode(
            (json.dumps(data, indent=2) + "\n").encode("utf-8")
        ).decode("ascii"),
        "branch": GITHUB_REF_NAME,
    }
    if existing_sha:
        payload["sha"] = existing_sha
    response = SESSION.put(url, headers=github_headers(), json=payload, timeout=20)
    response.raise_for_status()


def signal_id(message):
    """Stable ID from strategy/direction and the completed candle timestamp."""
    lines = message.splitlines()
    title = lines[0].strip() if lines else "unknown"
    candle_line = next(
        (line for line in lines if line.startswith("Completed candle (UTC):")),
        "",
    )
    candle_time = candle_line.partition(":")[2].strip()
    if not candle_time or candle_time == "unavailable":
        raise RuntimeError("Signal has no completed-candle timestamp; refusing to send an undeduplicated signal.")
    return f"{title}|{candle_time}"



def main():
    print("Starting XAU/USD scalping, swing and volatility-reaction checks.")
    if TEST_TELEGRAM_DELIVERY:
        telegram_send("✅ Telegram test successful: Klejsi Gold Signals bot can send messages.")
    signals = generate_signals()
    if not signals:
        print("No signal setup on this check; no trade signal sent.")
        return

    sent_ids, state_sha = load_signal_state()
    new_ids = set(sent_ids)
    delivered = 0
    for signal in signals:
        sid = signal_id(signal)
        if sid in new_ids:
            print(f"Duplicate signal skipped: {sid}")
            continue
        print(signal)
        telegram_send(signal)
        new_ids.add(sid)
        delivered += 1

    if new_ids != sent_ids:
        save_signal_state(new_ids, state_sha)
    print(f"Sent {delivered} new signal(s); skipped {len(signals) - delivered} duplicate(s).")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"BOT ERROR: {type(exc).__name__}: {exc}")
        raise

# Gold Signals Telegram Bot — prototype

This is a signal-only educational prototype. It does **not** place trades and is not a proven or backtested strategy.

## Files
- `bot.py` — basic heuristic using XAU/USD candles from Twelve Data and Telegram Bot API.
- `requirements.txt` — Python dependencies.

## Required environment variables
- `TELEGRAM_BOT_TOKEN` — secret token from BotFather. Never share it publicly.
- `TELEGRAM_CHAT_ID` — your Telegram chat ID.
- `TWELVE_DATA_API_KEY` — API key from Twelve Data.
- `CHECK_INTERVAL_SECONDS` — optional; defaults to 300 seconds.

## Important limitations
- The strategy is a simplistic heuristic, not validated for profitability.
- Market data symbol/availability depends on the Twelve Data account and plan; feed may differ from your broker's XAUUSD price.
- No automatic economic calendar/news filter is included.
- The 0.5% risk is only mentioned in the message; position sizing is not calculated.
- It needs a continuously running Python host. Uploading files to GitHub alone will not run it.
- Test only in demo and verify prices, spread, stop-loss distance, and news before acting.

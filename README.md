# Public market monitor

Public Coinbase Exchange crypto market monitor. It collects one authentication-free WebSocket snapshot for BTC, ETH and SOL in USD/EUR, then writes a static dashboard. The public site has no broker credentials or order functionality.

The public website remains read-only. A separate, local `trader` command supports BTC-USD spot research and an explicitly gated Coinbase Advanced Trade integration. It is not deployed by GitHub Actions.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
PYTHONPATH=src python3 -m monitor --seconds 15
```

Open `docs/index.html` after a collection. The dashboard has two browser-configurable, paper-only strategies: momentum follows a threshold move; mean reversion fades it. Both compare the latest quote with an earlier collected snapshot. Settings stay in local storage, and the most recent 96 snapshots are retained in `data/history.json`. A signal appears after the chosen lookback has enough observations. No trades are placed.

The GitHub Action refreshes the dashboard every 30 minutes. GitHub Pages publishes `/docs` from `main` at https://kotnala-harshit.github.io/public-market-monitor/; the repository About section links to it.

## Trading research and guarded live integration

```bash
PYTHONPATH=src python3 -m trader backtest
PYTHONPATH=src python3 -m trader backtest --strategy reversion
PYTHONPATH=src python3 -m trader plan
```

This uses completed hourly BTC-USD candles, compares the latest close with 24 hours earlier, and only models spot long/flat trades. Default threshold is 2%; signals at an hourly close execute at the *next* hourly open in the backtest. It starts with $10,000, caps a position at $1,000, and models 0.7% fees plus slippage **per side** (an assumption; your actual Coinbase fee tier varies). The backtest divides 90 days into an initial 60-day window and a later 30-day holdout. These short, historical results do not validate future profitability. The static website's browser-only strategy settings do **not** configure the private bot.

The live path is intentionally **not enabled or scheduled**. It requires a dedicated Coinbase Advanced portfolio holding only bot funds, an API key scoped to that portfolio with view/trade but **no transfer** permission, a private machine with persistent state, and explicit opt-in. Never put keys in this repository, the Pages site, or GitHub Actions. Install the optional SDK with `pip install -e '.[trade,dev]'`, then set `COINBASE_API_KEY` and `COINBASE_API_SECRET` as private environment variables. The live command requires `--portfolio-id`, `--execute`, and `LIVE_TRADING_ENABLED=YES`; do not run it until the strategy, venue, limits, credentials, and operational monitoring have been reviewed. It checks balances and product status, previews the order, caps estimated commission and price deviation, and records an attempt before submission. On uncertain outcomes it stops and requires manual reconciliation; it never retries blindly. The $9,800 portfolio-equity floor blocks new buys, not losses on an existing BTC position, and is **not** a guaranteed stop-loss. Use only one private host; the local lock does not coordinate multiple machines.

Coinbase's Advanced sandbox returns static mocked responses, so it cannot test fills or demonstrate an edge. Run a longer paper trial and check actual fee tier, taxes, connectivity, failures, and alerting before considering real capital. There is no guaranteed money-making strategy.

Coinbase documents its market-data WebSocket as publicly available without authentication for standard market-data channels: https://docs.cdp.coinbase.com/exchange/websocket-feed/overview

Commodity futures such as gold, crude oil, natural gas and grains are intentionally not labelled live here. CME's public quote pages are delayed by at least ten minutes. Add a licensed provider only if current commodity-futures data becomes necessary.

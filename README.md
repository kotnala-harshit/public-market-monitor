# Public market monitor

Paper-only monitor for public Coinbase Exchange crypto market data. It collects one authenticated-free WebSocket snapshot for BTC, ETH and SOL in USD/EUR, then writes a local dashboard. It has no broker credentials, order methods or live-money capability.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
PYTHONPATH=src python3 -m monitor --seconds 15
```

Open `docs/index.html` after a collection. The dashboard has two browser-configurable, paper-only strategies: momentum follows a threshold move; mean reversion fades it. Both compare the latest quote with an earlier collected snapshot. Settings stay in local storage, and the most recent 96 snapshots are retained in `data/history.json`. A signal appears after the chosen lookback has enough observations. No trades are placed.

The GitHub Action refreshes the dashboard every 30 minutes. To publish it, enable GitHub Pages in repository Settings → Pages with **Deploy from a branch**, branch **main**, folder **/docs**. Then set the repository About website to `https://kotnala-harshit.github.io/public-market-monitor/` once Pages is live.

Coinbase documents its market-data WebSocket as publicly available without authentication for standard market-data channels: https://docs.cdp.coinbase.com/exchange/websocket-feed/overview

Commodity futures such as gold, crude oil, natural gas and grains are intentionally not labelled live here. CME's public quote pages are delayed by at least ten minutes. Add a licensed provider only if current commodity-futures data becomes necessary.

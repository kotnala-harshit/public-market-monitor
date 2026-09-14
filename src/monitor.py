"""Public Coinbase market-data collector; it has no account or order functionality."""
from __future__ import annotations

import argparse
import html
import json
import time
from datetime import UTC, datetime
from pathlib import Path

ENDPOINT = "wss://ws-feed.exchange.coinbase.com"
PRODUCTS = ("BTC-USD", "ETH-USD", "SOL-USD", "BTC-EUR", "ETH-EUR")


def collect(products: tuple[str, ...] = PRODUCTS, seconds: int = 15) -> dict:
    import certifi
    import websocket

    socket = websocket.create_connection(ENDPOINT, timeout=5, sslopt={"ca_certs": certifi.where()})
    socket.send(json.dumps({"type": "subscribe", "channels": [{"name": "ticker", "product_ids": products}]}))
    deadline, quotes = time.monotonic() + seconds, {}
    try:
        while time.monotonic() < deadline and len(quotes) < len(products):
            message = json.loads(socket.recv())
            if message.get("type") == "ticker" and message.get("product_id") in products:
                quotes[message["product_id"]] = {"price": float(message["price"]), "timestamp": message["time"]}
    finally:
        socket.close()
    return {"collected_at": datetime.now(UTC).isoformat(), "provider": "Coinbase Exchange public WebSocket", "quotes": quotes}


def render(snapshot: dict, destination: Path) -> None:
    rows = "".join(f"<tr><td>{html.escape(symbol)}</td><td>{quote['price']:,.4f}</td><td>{html.escape(quote['timestamp'])}</td></tr>" for symbol, quote in snapshot["quotes"].items()) or "<tr><td colspan='3'>No quote collected.</td></tr>"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"""<!doctype html><meta charset='utf-8'><title>Public market monitor</title><style>body{{font:16px system-ui;max-width:800px;margin:40px auto;color:#172433}}table{{border-collapse:collapse;width:100%}}td,th{{padding:12px;border-bottom:1px solid #ccd5df;text-align:left}}small{{color:#586775}}</style><h1>Public crypto market monitor</h1><p>Read-only, no account or order connection.</p><table><tr><th>Product</th><th>Last price</th><th>Exchange timestamp</th></tr>{rows}</table><p><small>Provider: {html.escape(snapshot['provider'])}. Snapshot collected: {html.escape(snapshot['collected_at'])}. Commodity futures are deliberately excluded: public CME quotes are delayed.</small></p>""")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=15)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    snapshot = collect(seconds=args.seconds)
    data = args.root / "data" / "latest.json"
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_text(json.dumps(snapshot, indent=2))
    render(snapshot, args.root / "docs" / "index.html")
    print(json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    main()

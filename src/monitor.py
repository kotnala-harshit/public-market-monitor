"""Read-only Coinbase market monitor."""
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
            try:
                message = json.loads(socket.recv())
            except websocket.WebSocketTimeoutException:
                continue
            if message.get("type") == "ticker" and message.get("product_id") in products:
                quotes[message["product_id"]] = {"price": float(message["price"]), "timestamp": message["time"]}
    finally:
        socket.close()
    return {"collected_at": datetime.now(UTC).isoformat(), "provider": "Coinbase Exchange public WebSocket", "quotes": quotes}


def add_history(history: list[dict], snapshot: dict) -> list[dict]:
    if not snapshot["quotes"]:
        return history[-96:]
    row = {"at": snapshot["collected_at"], "prices": {symbol: quote["price"] for symbol, quote in snapshot["quotes"].items()}}
    return (history + [row])[-96:]


def render(snapshot: dict, destination: Path, history: list[dict] | None = None) -> None:
    cards = "".join(
        f'<article class="card" data-symbol="{html.escape(symbol)}"><div class="cardtop"><b>{html.escape(symbol.split("-")[0])}</b><span>{html.escape(symbol)}</span></div><strong>{quote["price"]:,.2f}</strong><small>{html.escape(symbol.split("-")[1])} · {html.escape(quote["timestamp"])}</small><em class="signal">Waiting for history</em></article>'
        for symbol, quote in snapshot["quotes"].items()
    ) or '<p>No quotes collected. Run the collector again.</p>'
    payload = json.dumps(history or []).replace("<", "\\u003c")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Public Market Monitor</title><style>
:root{{font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:#0b111a;color:#edf4fc}}*{{box-sizing:border-box}}body{{margin:0}}a{{color:#7cc9ff}}.wrap{{max-width:1160px;margin:auto;padding:0 24px 70px}}header{{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #263443;padding:26px 0}}.brand{{font-size:13px;font-weight:800;letter-spacing:.15em;text-transform:uppercase}}.brand:before{{content:'●';color:#49d7a2;margin-right:10px}}.pill{{border:1px solid #38624e;border-radius:30px;padding:7px 12px;color:#83e6b6;font-size:12px}}.hero{{padding:60px 0 36px}}.overline{{font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:#8ab3d3}}h1{{font-size:clamp(38px,6vw,70px);line-height:1.05;letter-spacing:-.055em;margin:13px 0}}.lead{{max-width:630px;line-height:1.6;color:#9fb0c2}}.meta{{display:flex;gap:20px;flex-wrap:wrap;color:#8ea3b8;font-size:13px;margin-top:24px}}h2{{font-size:21px;letter-spacing:-.02em;margin:0}}.sectionhead{{display:flex;justify-content:space-between;align-items:end;gap:16px;margin:28px 0 16px}}.hint{{color:#8ea3b8;font-size:13px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(205px,1fr));gap:14px}}.card,.panel{{background:#14202e;border:1px solid #2b3d50;border-radius:16px;padding:22px}}.cardtop{{display:flex;justify-content:space-between;align-items:center;color:#a9bdcf;font-size:12px}}.cardtop b{{display:grid;place-items:center;background:#223c50;color:#92d7ff;border-radius:10px;width:38px;height:38px;font-size:14px}}.card strong{{display:block;font-size:30px;letter-spacing:-.04em;margin:20px 0 5px}}small{{display:block;color:#8198ad;font-size:11px;min-height:34px;overflow-wrap:anywhere}}.signal{{display:inline-block;margin-top:16px;padding:6px 9px;border-radius:6px;background:#273a4a;color:#b3c3d1;font-size:12px;font-style:normal}}.up{{background:#173f35;color:#81eac1}}.down{{background:#482e37;color:#ffaab7}}.controls{{display:flex;gap:14px;flex-wrap:wrap}}label{{display:flex;flex-direction:column;gap:7px;color:#a7b8c8;font-size:12px}}select,input{{background:#0e1824;border:1px solid #3a5065;color:#edf4fc;border-radius:8px;padding:10px 12px;font:inherit;min-width:150px}}input{{width:145px}}.explain{{color:#91a6ba;font-size:13px;line-height:1.6;margin-bottom:0}}footer{{border-top:1px solid #263443;margin-top:48px;padding-top:22px;color:#859aaf;font-size:12px;line-height:1.7}}@media(max-width:540px){{.wrap{{padding:0 16px 50px}}.hero{{padding-top:40px}}.controls label,.controls input,.controls select{{width:100%}}}}
</style></head><body><div class="wrap"><header><div class="brand">Market / Monitor</div><span class="pill">● Paper only</span></header><main><section class="hero"><div class="overline">Coinbase Exchange · Public feed</div><h1>Markets at a glance.</h1><p class="lead">Public crypto quotes and transparent paper signals. No account connection, no orders, no real-money trading.</p><div class="meta"><span>Snapshot: {html.escape(snapshot["collected_at"])}</span><span>{html.escape(snapshot["provider"])}</span></div></section><section><div class="sectionhead"><h2>Latest prices</h2><span class="hint">Exchange timestamps on each card</span></div><div class="grid">{cards}</div></section><section><div class="sectionhead"><h2>Paper strategy</h2><span class="hint">Settings saved in this browser</span></div><div class="panel"><div class="controls"><label>Strategy<select id="strategy"><option value="momentum">Momentum</option><option value="reversion">Mean reversion</option></select></label><label>Lookback snapshots<input id="lookback" type="number" min="2" max="50" value="4"></label><label>Threshold (%)<input id="threshold" type="number" min="0.1" max="50" step="0.1" value="1"></label></div><p id="explain" class="explain"></p></div></section></main><footer>Signals compare the latest price with an earlier collected snapshot. Educational indicators only, not investment advice. Quotes can be stale between collections. Commodity futures are excluded because public CME quotes are delayed. <a href="https://github.com/kotnala-harshit/public-market-monitor">Source code</a>.</footer></div><script id="history" type="application/json">{payload}</script><script>
const history=JSON.parse(document.getElementById('history').textContent),strategy=document.getElementById('strategy'),lookback=document.getElementById('lookback'),threshold=document.getElementById('threshold');
try{{const saved=JSON.parse(localStorage.getItem('market-strategy')||'{{}}');if(['momentum','reversion'].includes(saved.strategy))strategy.value=saved.strategy;if(Number.isInteger(saved.lookback)&&saved.lookback>=2&&saved.lookback<=50)lookback.value=saved.lookback;if(Number.isFinite(saved.threshold)&&saved.threshold>=.1&&saved.threshold<=50)threshold.value=saved.threshold}}catch{{}}
function update(){{const n=Number(lookback.value),t=Number(threshold.value);if(!Number.isInteger(n)||n<2||n>50||!Number.isFinite(t)||t<.1||t>50)return;try{{localStorage.setItem('market-strategy',JSON.stringify({{strategy:strategy.value,lookback:n,threshold:t}}))}}catch{{}}document.getElementById('explain').textContent=(strategy.value==='momentum'?'Momentum follows':'Mean reversion fades')+' a move of at least '+t+'% versus '+n+' collected observations. Missing observations are ignored.';for(const card of document.querySelectorAll('.card')){{const prices=history.map(row=>row.prices[card.dataset.symbol]).filter(price=>Number.isFinite(price)&&price>0),badge=card.querySelector('.signal');if(prices.length<n){{badge.textContent='Need '+(n-prices.length)+' more snapshots';badge.className='signal';continue}}const change=(prices.at(-1)/prices.at(-n)-1)*100,direction=Math.abs(change)<t?'Neutral':(change>0)===(strategy.value==='momentum')?'Paper bullish':'Paper bearish';badge.textContent=direction+' · '+(change>=0?'+':'')+change.toFixed(2)+'%';badge.className='signal '+(direction==='Paper bullish'?'up':direction==='Paper bearish'?'down':'')}}}}
for(const control of [strategy,lookback,threshold])control.addEventListener('input',update);update();
</script></body></html>''')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=15)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    snapshot = collect(seconds=args.seconds)
    data = args.root / "data" / "latest.json"
    history_file = args.root / "data" / "history.json"
    data.parent.mkdir(parents=True, exist_ok=True)
    history = add_history(json.loads(history_file.read_text()) if history_file.exists() else [], snapshot)
    data.write_text(json.dumps(snapshot, indent=2))
    history_file.write_text(json.dumps(history, indent=2))
    render(snapshot, args.root / "docs" / "index.html", history)
    print(json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    main()

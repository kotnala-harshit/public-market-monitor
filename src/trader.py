"""One-shot BTC-USD spot strategy runner. Never import this from the public site/job."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import ssl
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from itertools import pairwise
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid5

import certifi

PRODUCT = "BTC-USD"
CAPITAL = Decimal(10000)
MAX_POSITION = Decimal(1000)
LOSS_FLOOR = Decimal(9800)
FEE_AND_SLIPPAGE = Decimal("0.007")  # Assumption per side, not an exchange quote.


def candles(days: int = 90) -> list[tuple[int, Decimal, Decimal]]:
    """Completed hourly Exchange candles, oldest first: (start, open, close)."""
    end = int(datetime.now(UTC).timestamp()) // 3600 * 3600
    start = end - days * 86400
    rows = {}
    for left in range(start, end, 299 * 3600):
        query = urlencode(
            {
                "start": datetime.fromtimestamp(left, UTC).isoformat(),
                "end": datetime.fromtimestamp(min(left + 299 * 3600, end), UTC).isoformat(),
                "granularity": 3600,
            }
        )
        request = Request(
            f"https://api.exchange.coinbase.com/products/{PRODUCT}/candles?{query}",
            headers={"User-Agent": "public-market-monitor/0.2"},
        )
        with urlopen(
            request, timeout=15, context=ssl.create_default_context(cafile=certifi.where())
        ) as response:
            for row in json.load(response):
                stamp = int(row[0])
                if start <= stamp < end:
                    rows[stamp] = (stamp, Decimal(str(row[3])), Decimal(str(row[4])))
    ordered = [rows[t] for t in sorted(rows)]
    if len(ordered) < days * 20 or any(b[0] - a[0] != 3600 for a, b in pairwise(ordered)):
        raise ValueError("Incomplete hourly history; refusing to infer missing candles")
    return ordered


def signal(closes: list[Decimal], lookback: int, threshold: Decimal, strategy: str) -> str:
    if (
        strategy not in ("momentum", "reversion")
        or not 2 <= lookback <= 72
        or not threshold.is_finite()
        or not 0 < threshold < 1
    ):
        raise ValueError("Invalid strategy configuration")
    if len(closes) < lookback:
        return "hold"
    change = closes[-1] / closes[-lookback] - 1
    if abs(change) < threshold:
        return "hold"
    return "buy" if (change > 0) == (strategy == "momentum") else "sell"


def backtest(
    rows: list[tuple[int, Decimal, Decimal]], strategy: str, lookback: int, threshold: Decimal
) -> dict:
    """Signal at close; execute at next hour's open with costs and no leverage."""
    cash, btc, peak, max_drawdown, trades = CAPITAL, Decimal(0), CAPITAL, Decimal(0), 0
    for i in range(lookback - 1, len(rows) - 1):
        action = signal(
            [r[2] for r in rows[i - lookback + 1 : i + 1]], lookback, threshold, strategy
        )
        price = rows[i + 1][1]
        if (
            action == "buy"
            and not btc
            and cash >= MAX_POSITION * (1 + FEE_AND_SLIPPAGE)
            and cash >= LOSS_FLOOR
        ):
            cash -= MAX_POSITION * (1 + FEE_AND_SLIPPAGE)
            btc = MAX_POSITION / price
            trades += 1
        elif action == "sell" and btc:
            cash += btc * price * (1 - FEE_AND_SLIPPAGE)
            btc = Decimal(0)
            trades += 1
        equity = cash + btc * price * (1 - FEE_AND_SLIPPAGE)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, 1 - equity / peak)
    final = cash + btc * rows[-1][2] * (1 - FEE_AND_SLIPPAGE)
    return {
        "start": rows[0][0],
        "end": rows[-1][0],
        "starting_usd": str(CAPITAL),
        "ending_usd": str(final.quantize(Decimal("0.01"))),
        "return_pct": str(((final / CAPITAL - 1) * 100).quantize(Decimal("0.01"))),
        "max_drawdown_pct": str((max_drawdown * 100).quantize(Decimal("0.01"))),
        "trades": trades,
    }


def as_dict(response) -> dict:
    return response.to_dict() if hasattr(response, "to_dict") else dict(response)


def save_state(path: Path, state: dict) -> None:
    temp = path.with_suffix(".tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(state, output)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, path)


def live_once(
    client,
    rows: list[tuple[int, Decimal, Decimal]],
    state_path: Path,
    portfolio_id: str,
    strategy: str,
    lookback: int,
    threshold: Decimal,
) -> dict:
    """Only for a dedicated portfolio with USD and bot-owned BTC; fail closed on ambiguity."""
    if len(rows) < lookback or rows[-1][0] < int(datetime.now(UTC).timestamp()) - 7200:
        raise ValueError("Market data is stale")
    with state_path.with_suffix(".lock").open("a+") as lock:
        # ponytail: one local lock; use a centralized lock before running multiple hosts.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        if state and state.get("portfolio_id") != portfolio_id:
            raise ValueError("State belongs to another portfolio")
        if state.get("status") == "pending":
            raise ValueError("Previous order outcome unknown; reconcile manually before retrying")
        if state.get("status") == "submitted":
            order = as_dict(client.get_order(state["order_id"]))["order"]
            if order["status"] != "FILLED":
                raise ValueError("Previous order not filled; reconcile manually before retrying")
            state["owned_btc"] = (
                str(Decimal(order["filled_size"])) if state["side"] == "buy" else "0"
            )
            state["status"] = "ready"
            save_state(state_path, state)
        stamp = rows[-1][0]
        if state.get("last_candle") == stamp:
            return {"action": "hold", "reason": "Already processed this candle"}
        permissions = as_dict(client.get_api_key_permissions())
        if (
            permissions.get("portfolio_uuid") != portfolio_id
            or not permissions.get("can_trade")
            or permissions.get("can_transfer")
        ):
            raise ValueError(
                "Use a trade/view-only key for the specified dedicated portfolio, without transfer permission"
            )
        product = as_dict(client.get_product(PRODUCT, get_tradability_status=True))
        if product.get("product_type") != "SPOT" or any(
            product.get(flag) is not False
            for flag in (
                "is_disabled",
                "trading_disabled",
                "cancel_only",
                "limit_only",
                "view_only",
                "auction_mode",
            )
        ):
            raise ValueError("BTC-USD spot market is not available for market orders")
        accounts = as_dict(client.get_accounts(limit=250))
        if accounts.get("has_next"):
            raise ValueError("Account list is incomplete")
        outstanding = as_dict(
            client.list_orders(
                product_ids=[PRODUCT],
                order_status=["PENDING", "OPEN", "QUEUED", "CANCEL_QUEUED", "EDIT_QUEUED"],
                limit=1,
            )
        )
        if "orders" not in outstanding or outstanding.get("orders") or outstanding.get("has_next"):
            raise ValueError("Existing BTC-USD order is still open; refusing another order")
        balances = {
            a["currency"]: Decimal(a["available_balance"]["value"])
            for a in accounts["accounts"]
            if a.get("active") and a.get("ready")
        }
        if (
            "USD" not in balances
            or "BTC" not in balances
            or sum(
                a.get("currency") in ("USD", "BTC") and a.get("active") and a.get("ready")
                for a in accounts["accounts"]
            )
            != 2
        ):
            raise ValueError("Portfolio needs both USD and BTC accounts")
        usd, btc = balances["USD"], balances["BTC"]
        price = Decimal(product["price"])
        if (
            not price.is_finite()
            or price <= 0
            or not 0 <= usd <= CAPITAL * 2
            or not 0 <= btc * price <= MAX_POSITION * Decimal("1.1")
        ):
            raise ValueError("Unexpected balance or price; check the dedicated portfolio")
        if not state and btc:
            raise ValueError(
                "Starting portfolio already holds BTC; move it out before first live run"
            )
        owned = Decimal(state.get("owned_btc", "0"))
        if btc > owned + Decimal(product["base_increment"]):
            raise ValueError("Portfolio contains BTC not acquired by this bot; refusing to sell it")
        action = signal([r[2] for r in rows], lookback, threshold, strategy)
        if action == "buy" and btc:
            action = "hold"
        if action == "buy" and (
            usd < MAX_POSITION * Decimal("1.01") or usd + btc * price < LOSS_FLOOR
        ):
            action = "hold"
        if action == "sell" and not btc:
            action = "hold"
        if action == "hold":
            save_state(
                state_path,
                {
                    "portfolio_id": portfolio_id,
                    "last_candle": stamp,
                    "status": "ready",
                    "owned_btc": str(owned),
                },
            )
            return {"action": "hold", "reason": "Signal or risk limit"}
        if action == "buy":
            size = MAX_POSITION.quantize(Decimal(product["quote_increment"]), rounding=ROUND_DOWN)
            if not Decimal(product["quote_min_size"]) <= size <= Decimal(product["quote_max_size"]):
                raise ValueError("Buy size violates product limits")
            size_arg = {"quote_size": str(size)}
        else:
            size = btc.quantize(Decimal(product["base_increment"]), rounding=ROUND_DOWN)
            if not Decimal(product["base_min_size"]) <= size <= Decimal(product["base_max_size"]):
                raise ValueError("Sell size violates product limits")
            size_arg = {"base_size": str(size)}
        preview = as_dict(
            getattr(client, f"preview_market_order_{action}")(product_id=PRODUCT, **size_arg)
        )
        if (
            preview.get("errs")
            or preview.get("warning")
            or Decimal(preview["commission_total"]) > MAX_POSITION * Decimal("0.01")
        ):
            raise ValueError("Order preview flagged an error, warning, or fee above 1%")
        estimated = Decimal(preview["est_average_filled_price"])
        if not estimated.is_finite() or abs(estimated / price - 1) > Decimal("0.01"):
            raise ValueError("Preview price differs from current price by over 1%")
        order_id = str(
            uuid5(
                NAMESPACE_URL,
                f"{portfolio_id}:{PRODUCT}:{strategy}:{lookback}:{threshold}:{stamp}:{action}",
            )
        )
        # Persist before posting: an uncertain response must never trigger an automatic second order.
        save_state(
            state_path,
            {
                "portfolio_id": portfolio_id,
                "last_candle": stamp,
                "status": "pending",
                "client_order_id": order_id,
                "owned_btc": str(owned),
            },
        )
        result = as_dict(
            getattr(client, f"market_order_{action}")(
                client_order_id=order_id, product_id=PRODUCT, **size_arg
            )
        )
        if not result.get("success") or not result.get("success_response", {}).get("order_id"):
            raise ValueError(
                "Order response was not successful; reconcile manually before retrying"
            )
        save_state(
            state_path,
            {
                "portfolio_id": portfolio_id,
                "last_candle": stamp,
                "status": "submitted",
                "order_id": result["success_response"]["order_id"],
                "side": action,
                "owned_btc": str(owned),
            },
        )
        return {
            "action": action,
            "size": str(size),
            "order_id": result["success_response"]["order_id"],
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="BTC-USD spot research and guarded one-shot trading"
    )
    parser.add_argument("mode", choices=("backtest", "plan", "live"))
    parser.add_argument("--strategy", choices=("momentum", "reversion"), default="momentum")
    parser.add_argument(
        "--lookback", type=int, default=25, help="Hourly closes, 25 means a 24-hour comparison"
    )
    parser.add_argument(
        "--threshold", type=Decimal, default=Decimal("0.02"), help="Fraction; 0.02 means 2 percent"
    )
    parser.add_argument(
        "--portfolio-id", help="Dedicated Coinbase Advanced portfolio UUID, required for live mode"
    )
    parser.add_argument("--state", type=Path, default=Path("data/trader-state.json"))
    parser.add_argument(
        "--execute", action="store_true", help="Explicitly enable real orders in live mode"
    )
    args = parser.parse_args()
    if not 2 <= args.lookback <= 72 or not args.threshold.is_finite() or not 0 < args.threshold < 1:
        parser.error("Lookback must be 2-72 and threshold must be between 0 and 1")
    if args.mode == "live" and (
        not args.execute or os.getenv("LIVE_TRADING_ENABLED") != "YES" or not args.portfolio_id
    ):
        parser.error("Live mode requires --execute, --portfolio-id and LIVE_TRADING_ENABLED=YES")
    rows = candles(90 if args.mode == "backtest" else 3)
    if args.mode == "backtest":
        split = len(rows) * 2 // 3
        print(
            json.dumps(
                {
                    "strategy": args.strategy,
                    "lookback": args.lookback,
                    "threshold": str(args.threshold),
                    "assumed_cost_per_side_pct": str(FEE_AND_SLIPPAGE * 100),
                    "train": backtest(rows[:split], args.strategy, args.lookback, args.threshold),
                    "holdout": backtest(
                        rows[split - args.lookback + 1 :],
                        args.strategy,
                        args.lookback,
                        args.threshold,
                    ),
                },
                indent=2,
            )
        )
    elif args.mode == "plan":
        print(
            json.dumps(
                {
                    "as_of": datetime.fromtimestamp(rows[-1][0] + 3600, UTC).isoformat(),
                    "product": PRODUCT,
                    "hypothetical_action_if_flat": signal(
                        [r[2] for r in rows], args.lookback, args.threshold, args.strategy
                    ),
                    "max_position_usd": str(MAX_POSITION),
                    "note": "No account consulted; no order submitted",
                },
                indent=2,
            )
        )
    else:
        from coinbase.rest import RESTClient

        key, secret = os.getenv("COINBASE_API_KEY"), os.getenv("COINBASE_API_SECRET")
        if not key or not secret:
            parser.error("Set COINBASE_API_KEY and COINBASE_API_SECRET outside the repository")
        args.state.parent.mkdir(parents=True, exist_ok=True)
        client = RESTClient(api_key=key, api_secret=secret.replace("\\n", "\n"), timeout=15)
        print(
            json.dumps(
                live_once(
                    client,
                    rows,
                    args.state,
                    args.portfolio_id,
                    args.strategy,
                    args.lookback,
                    args.threshold,
                )
            )
        )


if __name__ == "__main__":
    main()

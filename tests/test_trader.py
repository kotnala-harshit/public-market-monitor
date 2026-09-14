import json
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from trader import backtest, live_once, paper_once, reconcile, signal


def test_signal_and_backtest_next_open() -> None:
    assert signal([D(100), D(103)], 2, D("0.02"), "momentum") == "buy"
    assert signal([D(100), D(103)], 2, D("0.02"), "reversion") == "sell"
    rows = [(i * 3600, D(p), D(p)) for i, p in enumerate((100, 103, 110, 90, 90))]
    result = backtest(rows, "momentum", 2, D("0.02"))
    assert result["trades"] == 2
    assert D(result["ending_usd"]) < D(10000)  # Next open at 110, not signal close at 103.


def test_paper_only_fills_prior_signal_at_next_open(tmp_path) -> None:
    state = tmp_path / "paper.json"
    rows = [(i * 3600, D(p), D(p)) for i, p in enumerate((100, 103, 110))]
    first = paper_once(rows[:2], state, "momentum", 2, D("0.02"))
    assert first["next_action"] == "buy"
    assert first["trades"] == 0
    second = paper_once(rows, state, "momentum", 2, D("0.02"))
    assert second["filled_action"] == "buy"
    assert second["trades"] == 1
    assert D(second["btc"]) == D(1000) / D(110)
    assert paper_once(rows, state, "momentum", 2, D("0.02")) == second
    with pytest.raises(ValueError, match="settings changed"):
        paper_once(rows, state, "reversion", 2, D("0.02"))
    with pytest.raises(ValueError, match="Missed an hourly candle"):
        paper_once(rows + [(4 * 3600, D(90), D(90))], state, "momentum", 2, D("0.02"))


def test_live_rejects_ambiguous_order_before_retry(tmp_path) -> None:
    stamp = int(datetime.now(UTC).timestamp()) // 3600 * 3600 - 3600
    rows = [(stamp - 3600, D(100), D(100)), (stamp, D(103), D(103))]

    class Exchange:
        calls = 0
        found = False
        order_status = "FILLED"

        def get_api_key_permissions(self):
            return {"portfolio_uuid": "dedicated", "can_trade": True, "can_transfer": False}

        def get_product(self, *args, **kwargs):
            return {
                "product_type": "SPOT",
                "price": "103",
                "quote_increment": "0.01",
                "quote_min_size": "1",
                "quote_max_size": "10000",
                "base_increment": "0.00000001",
                "is_disabled": False,
                "trading_disabled": False,
                "cancel_only": False,
                "limit_only": False,
                "view_only": False,
                "auction_mode": False,
            }

        def get_accounts(self, **kwargs):
            return {
                "has_next": False,
                "accounts": [
                    {
                        "currency": currency,
                        "active": True,
                        "ready": True,
                        "available_balance": {"value": amount},
                    }
                    for currency, amount in (("USD", "10000"), ("BTC", "0"))
                ],
            }

        def list_orders(self, **kwargs):
            if self.found and "start_date" in kwargs:
                return {
                    "orders": [{"client_order_id": self.client_order_id, "order_id": "exchange-1"}],
                    "has_next": False,
                }
            return {"orders": [], "has_next": False}

        def get_order(self, order_id):
            return {
                "order": {
                    "order_id": order_id,
                    "client_order_id": self.client_order_id,
                    "product_id": "BTC-USD",
                    "side": "BUY",
                    "status": self.order_status,
                    "filled_size": "9.7",
                    "average_filled_price": "103",
                }
            }

        def preview_market_order_buy(self, **kwargs):
            return {
                "errs": [],
                "warning": [],
                "commission_total": "6",
                "est_average_filled_price": "103",
            }

        def market_order_buy(self, **kwargs):
            self.calls += 1
            self.client_order_id = kwargs["client_order_id"]
            raise TimeoutError("Unknown outcome")

    exchange = Exchange()
    state = tmp_path / "state.json"
    with pytest.raises(TimeoutError):
        live_once(exchange, rows, state, "dedicated", "momentum", 2, D("0.02"))
    with pytest.raises(ValueError, match="outcome unknown"):
        live_once(exchange, rows, state, "dedicated", "momentum", 2, D("0.02"))
    assert exchange.calls == 1
    with pytest.raises(ValueError, match="Order not found"):
        reconcile(exchange, state, "dedicated")
    assert json.loads(state.read_text())["status"] == "pending"
    exchange.found = True
    exchange.order_status = "OPEN"
    with pytest.raises(ValueError, match="not filled"):
        reconcile(exchange, state, "dedicated")
    assert json.loads(state.read_text())["status"] == "pending"
    exchange.order_status = "FILLED"
    assert reconcile(exchange, state, "dedicated") == {
        "status": "ready",
        "order_id": "exchange-1",
        "owned_btc": "9.7",
    }
    assert (
        live_once(exchange, rows, state, "dedicated", "momentum", 2, D("0.02"))["action"] == "hold"
    )
    assert exchange.calls == 1


def test_live_never_sells_unowned_btc(tmp_path) -> None:
    stamp = int(datetime.now(UTC).timestamp()) // 3600 * 3600 - 3600
    rows = [(stamp - 3600, D(103), D(103)), (stamp, D(100), D(100))]
    state = tmp_path / "state.json"
    state.write_text('{"portfolio_id":"dedicated","status":"ready","owned_btc":"0"}')

    class Exchange:
        def get_api_key_permissions(self):
            return {"portfolio_uuid": "dedicated", "can_trade": True, "can_transfer": False}

        def get_product(self, *args, **kwargs):
            return {
                "product_type": "SPOT",
                "price": "100",
                "base_increment": "0.00000001",
                "is_disabled": False,
                "trading_disabled": False,
                "cancel_only": False,
                "limit_only": False,
                "view_only": False,
                "auction_mode": False,
            }

        def get_accounts(self, **kwargs):
            return {
                "has_next": False,
                "accounts": [
                    {
                        "currency": currency,
                        "active": True,
                        "ready": True,
                        "available_balance": {"value": amount},
                    }
                    for currency, amount in (("USD", "9900"), ("BTC", "1"))
                ],
            }

        def list_orders(self, **kwargs):
            return {"orders": [], "has_next": False}

    with pytest.raises(ValueError, match="not acquired by this bot"):
        live_once(Exchange(), rows, state, "dedicated", "momentum", 2, D("0.02"))


def test_reconcile_submitted_sell_preserves_partial_ownership(tmp_path) -> None:
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "portfolio_id": "dedicated",
                "status": "submitted",
                "side": "sell",
                "order_id": "exchange-2",
                "client_order_id": "bot-2",
                "owned_btc": "0.01",
            }
        )
    )

    class Exchange:
        def get_api_key_permissions(self):
            return {"portfolio_uuid": "dedicated", "can_transfer": False}

        def get_order(self, order_id):
            return {
                "order": {
                    "order_id": order_id,
                    "client_order_id": "bot-2",
                    "product_id": "BTC-USD",
                    "side": "SELL",
                    "status": "FILLED",
                    "filled_size": "0.009",
                }
            }

    assert reconcile(Exchange(), state, "dedicated")["owned_btc"] == "0.001"

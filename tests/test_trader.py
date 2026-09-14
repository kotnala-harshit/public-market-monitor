from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from trader import backtest, live_once, signal


def test_signal_and_backtest_next_open() -> None:
    assert signal([D(100), D(103)], 2, D("0.02"), "momentum") == "buy"
    assert signal([D(100), D(103)], 2, D("0.02"), "reversion") == "sell"
    rows = [(i * 3600, D(p), D(p)) for i, p in enumerate((100, 103, 110, 90, 90))]
    result = backtest(rows, "momentum", 2, D("0.02"))
    assert result["trades"] == 2
    assert D(result["ending_usd"]) < D(10000)  # Next open at 110, not signal close at 103.


def test_live_rejects_ambiguous_order_before_retry(tmp_path) -> None:
    stamp = int(datetime.now(UTC).timestamp()) // 3600 * 3600 - 3600
    rows = [(stamp - 3600, D(100), D(100)), (stamp, D(103), D(103))]

    class Exchange:
        calls = 0

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
            return {"orders": [], "has_next": False}

        def preview_market_order_buy(self, **kwargs):
            return {
                "errs": [],
                "warning": [],
                "commission_total": "6",
                "est_average_filled_price": "103",
            }

        def market_order_buy(self, **kwargs):
            self.calls += 1
            raise TimeoutError("Unknown outcome")

    exchange = Exchange()
    state = tmp_path / "state.json"
    with pytest.raises(TimeoutError):
        live_once(exchange, rows, state, "dedicated", "momentum", 2, D("0.02"))
    with pytest.raises(ValueError, match="outcome unknown"):
        live_once(exchange, rows, state, "dedicated", "momentum", 2, D("0.02"))
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

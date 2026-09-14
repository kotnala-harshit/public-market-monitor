from pathlib import Path

from monitor import add_history, render


def test_render_includes_public_quotes(tmp_path: Path) -> None:
    destination = tmp_path / "index.html"
    render({"collected_at": "2026-09-14T00:00:00+00:00", "provider": "Coinbase", "quotes": {"BTC-USD": {"price": 100_000, "timestamp": "2026-09-14T00:00:00+00:00"}}}, destination)
    assert "BTC-USD" in destination.read_text()


def test_history_keeps_only_collected_prices() -> None:
    snapshot = {"collected_at": "now", "quotes": {"BTC-USD": {"price": 100}}}
    assert add_history([], snapshot) == [{"at": "now", "prices": {"BTC-USD": 100}}]
    assert add_history([{"at": "before", "prices": {}}], {"quotes": {}}) == [{"at": "before", "prices": {}}]

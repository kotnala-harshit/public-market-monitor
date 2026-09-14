from pathlib import Path

from monitor import render


def test_render_includes_public_quotes(tmp_path: Path) -> None:
    destination = tmp_path / "index.html"
    render({"collected_at": "2026-09-14T00:00:00+00:00", "provider": "Coinbase", "quotes": {"BTC-USD": {"price": 100_000, "timestamp": "2026-09-14T00:00:00+00:00"}}}, destination)
    assert "BTC-USD" in destination.read_text()

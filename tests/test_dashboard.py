from __future__ import annotations

from pathlib import Path

from symphony_dbcli.dashboard import render_index
from symphony_dbcli.store import Store


def test_dashboard_uses_static_css(tmp_path: Path) -> None:
    store = Store(tmp_path / "symphony.db")
    store.init()

    html = render_index(store)

    assert '<link rel="stylesheet" href="/static/dashboard.css"' in html
    assert "<style>" not in html
    assert "Recent Attempts" in html

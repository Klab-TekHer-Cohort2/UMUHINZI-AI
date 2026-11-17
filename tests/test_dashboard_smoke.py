"""Smoke test for the Streamlit dashboard.

This does not click buttons; it simply makes sure the page code runs without
exceptions. The backend HTTP calls are tested separately.
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard" / "app.py"


def test_dashboard_loads_without_exceptions():
    app = AppTest.from_file(str(DASHBOARD), default_timeout=30)
    app.run()

    assert len(app.exception) == 0
    assert app.title[0].value == "Umuhinzi AI"
    assert len(app.tabs) == 2

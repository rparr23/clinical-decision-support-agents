"""Browser test: start the web server and drive the UI with Playwright (Chromium)."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "test-results" / "screenshots"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    env = os.environ | {"CDS_MODE": "offline", "CDS_FEEDBACK_PATH": str(ROOT / "var" / "e2e-feedback.jsonl")}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.server:app", "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield url
    proc.terminate()


@pytest.fixture(scope="module")
def page():
    with playwright.sync_playwright() as p:
        exe = os.getenv("CHROMIUM_PATH")
        try:
            browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        except Exception:
            pytest.skip("Chromium not available")
        pg = browser.new_page(viewport={"width": 1440, "height": 1000})
        yield pg
        browser.close()


def test_ask_flow(server, page):
    page.goto(server)
    page.wait_for_selector(".example")
    assert page.locator("#brand-name").inner_text() == "ClearPath CDS"
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / "home.png"))
    page.locator(".example").nth(3).click()
    ans = page.wait_for_selector("[data-testid=answer]")
    text = ans.inner_text()
    assert "COPD, home nebulizer and oxygen" in text and "E1390" in text
    assert page.locator("#trace li").count() >= 4
    assert page.locator("#sources li").count() >= 3
    page.locator(".feedback button").first.click()
    page.wait_for_selector("text=Saved, thanks.")
    page.screenshot(path=str(SHOTS / "multi-agent-answer.png"), full_page=True)


def test_order_check_flow(server, page):
    page.goto(server)
    page.click("[data-tab=order]")
    page.wait_for_selector("#chart-card h4")
    page.select_option("#patient-select", "P-0001")
    page.click("#order-btn")
    v = page.wait_for_selector("[data-testid=verdict]")
    assert "Not supported" in v.inner_text()
    page.select_option("#patient-select", "P-0002")
    page.wait_for_function("document.querySelector('#chart-card h4').innerText.includes('P-0002')")
    page.click("#order-btn")
    page.wait_for_function("document.querySelector('[data-testid=verdict]').innerText.includes('Review needed')")
    page.screenshot(path=str(SHOTS / "order-check.png"), full_page=True)


def test_report_and_eval_flow(server, page):
    page.goto(server)
    page.click("[data-tab=report]")
    page.click("text=Critical finding not communicated")
    page.click("#report-btn")
    v = page.wait_for_selector("[data-testid=report-verdict]")
    assert "critical gap" in v.inner_text()
    page.screenshot(path=str(SHOTS / "report-check.png"), full_page=True)
    page.click("[data-tab=eval]")
    page.click("#eval-btn")
    m = page.wait_for_selector("[data-testid=metrics]")
    assert m.inner_text().count("Pass") == 6
    page.screenshot(path=str(SHOTS / "evaluation.png"), full_page=True)

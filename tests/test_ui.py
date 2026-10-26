"""The assistant page in a real browser, at phone width, with no model.

Runs only where Playwright and a browser are installed (the `ui` job in CI); everywhere
else it is skipped. It starts the real app in a thread, then taps through a guided
conversation the way a person would and checks what they would see: Tamil first, big
buttons, no sideways scrolling, a result at the end, and no script errors on the way.
Screenshots land in ui-screenshots/ for a person to look at.
"""

import threading
from pathlib import Path

import pytest

pytest.importorskip("flask")
playwright = pytest.importorskip("playwright.sync_api")

from werkzeug.serving import make_server  # noqa: E402

from tn_schemematch.web import create_app  # noqa: E402

SHOTS = Path(__file__).resolve().parent.parent / "ui-screenshots"
PHONE = {"width": 390, "height": 844}


@pytest.fixture(scope="module")
def base_url(kb, spec, tmp_path_factory):
    app = create_app(kb=kb, spec=spec, client=None,
                     vault_dir=tmp_path_factory.mktemp("vault"))
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport=PHONE, locale="ta-IN")
    page = context.new_page()
    page.errors = []
    page.on("pageerror", lambda exc: page.errors.append(str(exc)))
    page.on("console", lambda msg: page.errors.append(msg.text) if msg.type == "error" else None)
    yield page
    context.close()


def no_sideways_scroll(page):
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


def answer_current_question(page):
    """Tap the first sensible answer for whatever the open question is."""
    if page.locator("#number-input").count():
        page.fill("#number-input", "1")
        page.locator(".number-row .btn.primary").click()
    elif page.locator(".answer-btn").count():
        page.locator(".answer-btn").first.click()
    else:
        return False
    page.wait_for_load_state("networkidle")
    return True


def test_a_guided_conversation_on_a_phone(page, base_url):
    SHOTS.mkdir(exist_ok=True)
    page.goto(base_url + "/")
    page.wait_for_selector(".question-text")
    assert page.evaluate("document.documentElement.lang") == "ta"
    question = page.inner_text(".question-text")
    assert any("஀" <= ch <= "௿" for ch in question), question
    assert no_sideways_scroll(page)
    page.screenshot(path=str(SHOTS / "1-first-question.png"), full_page=True)

    # The first question is a number: age.
    page.fill("#number-input", "68")
    page.locator(".number-row .btn.primary").click()
    page.wait_for_load_state("networkidle")
    page.screenshot(path=str(SHOTS / "2-second-question.png"), full_page=True)

    for _ in range(12):
        if not answer_current_question(page):
            break
    assert no_sideways_scroll(page)

    page.click("#result-btn")
    page.wait_for_selector(".result-head")
    page.screenshot(path=str(SHOTS / "3-result.png"), full_page=True)
    assert no_sideways_scroll(page)
    assert page.errors == []


def test_answer_buttons_are_big_enough_to_tap(page, base_url):
    page.goto(base_url + "/")
    page.wait_for_selector(".question-text")
    answer_current_question(page)  # move past the number question to a button question
    page.wait_for_selector(".answer-btn")
    box = page.locator(".answer-btn").first.bounding_box()
    assert box["height"] >= 56


def test_language_switch_rewords_the_open_question(page, base_url):
    page.goto(base_url + "/")
    page.wait_for_selector(".question-text")
    page.click("#lang-switch")
    page.wait_for_function("document.documentElement.lang === 'en'")
    page.wait_for_function(
        "!/[஀-௿]/.test(document.querySelector('.question-text').textContent)")
    SHOTS.mkdir(exist_ok=True)
    page.screenshot(path=str(SHOTS / "4-english.png"), full_page=True)
    assert page.errors == []


def test_the_app_is_installable(page, base_url):
    response = page.request.get(base_url + "/static/manifest.webmanifest")
    assert response.ok and response.json()["start_url"] == "/"
    worker = page.request.get(base_url + "/sw.js")
    assert worker.ok and "javascript" in worker.headers["content-type"]

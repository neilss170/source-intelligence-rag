"""Browser smoke test of the running stack (docker compose up), through nginx.

Signs up, uploads a document, streams a cited answer, stops one, reloads,
signs out and in, and checks for console errors. Uses a real model call.

    pip install playwright && playwright install chromium
    python e2e/ui_flow.py backend/evaluation/documents/operations_report_2025.md

import random
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
REPORT = Path(sys.argv[1])
BASE = "http://127.0.0.1:8080/"
email = f"ui-{random.randint(10000, 99999)}@example.com"
problems = []


def watch(page):
    page.on(
        "console",
        lambda m: problems.append(f"{m.type}: {m.text[:200]}")
        if m.type in ("error", "warning")
        else None,
    )
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1366, "height": 860})
    watch(page)

    page.goto(BASE, wait_until="networkidle")
    expect(page.get_by_role("heading", name="Welcome back")).to_be_visible()
    page.screenshot(path=str(OUT / "ui-1-signin.png"))

    page.get_by_role("button", name="Create an account").click()
    page.get_by_label("Name").fill("Neil Sharma")
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password").fill("short")
    page.get_by_role("button", name="Create account").click()
    page.wait_for_timeout(400)
    still_on_form = page.get_by_role("button", name="Create account").is_visible()
    page.get_by_label("Password").fill("correct horse battery")
    page.get_by_role("button", name="Create account").click()
    expect(page.locator(".greeting h1")).to_contain_text("Neil")
    print("short password kept on form:", still_on_form)
    print("greeting:", page.locator(".greeting h1").inner_text().replace("\n", " "))

    page.locator("input[type=file]").set_input_files(str(REPORT))
    expect(page.locator(".doc-pill")).to_have_text(re.compile(r"^\s*1 document$"), timeout=60000)
    print("document pill:", page.locator(".doc-pill").inner_text())

    textarea = page.get_by_label("Ask a question")
    textarea.fill("How did workplace injuries change compared to the year before?")
    started = time.time()
    textarea.press("Enter")
    status_seen = None
    lengths = []
    for _ in range(600):
        status = page.locator(".thinking-status")
        if status_seen is None and status.count():
            status_seen = status.first.inner_text()
        copy = page.locator(".answer-copy")
        if copy.count():
            lengths.append(len(copy.first.inner_text()))
        if page.locator(".answer-meta").count():
            break
        page.wait_for_timeout(50)
    elapsed = round(time.time() - started, 1)
    growth = sorted(set(lengths))
    print(f"status shown: {status_seen!r}; answer grew through {len(growth)} sizes; done in {elapsed}s")
    print("answer:", page.locator(".answer-copy").first.inner_text()[:150])
    page.get_by_role("button", name="1 source").or_(
        page.get_by_role("button", name="2 sources")
    ).first.click()
    page.screenshot(path=str(OUT / "ui-2-answer.png"))

    textarea.fill("Summarise every section of the report in detail, one paragraph each.")
    textarea.press("Enter")
    stop = page.get_by_role("button", name="Stop answering")
    expect(stop).to_be_visible()
    page.wait_for_timeout(300)
    stop.click()
    expect(page.locator(".meta-note", has_text="Stopped")).to_be_visible(timeout=10000)
    print("stop button: answer marked Stopped")

    page.reload(wait_until="networkidle")
    page.get_by_role("button", name="How did workplace injuries", exact=False).first.click()
    expect(page.locator(".question").first).to_contain_text("workplace injuries")
    print("after reload, chat restored with", page.locator(".question").count(), "question(s)")

    page.get_by_role("button", name="Sign out").click()
    expect(page.get_by_role("heading", name="Welcome back")).to_be_visible()
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password").fill("correct horse battery")
    page.get_by_role("button", name="Sign in").click()
    expect(page.locator(".chat-row")).to_have_count(1, timeout=10000)
    print("signed out and back in; chats:", page.locator(".chat-row").count())

    phone = browser.new_page(viewport={"width": 390, "height": 844})
    watch(phone)
    phone.context.add_cookies(page.context.cookies())
    phone.goto(BASE, wait_until="networkidle")
    phone.screenshot(path=str(OUT / "ui-3-phone.png"))
    browser.close()

print("console problems:", problems or "none")

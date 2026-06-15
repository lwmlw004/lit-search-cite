#!/usr/bin/env python3
"""
Google Scholar search via Playwright.

First-time setup opens a real browser so you can solve any CAPTCHA.
Subsequent searches run completely headless using saved cookies.

Usage:
    python scripts/google-scholar.py --setup                        # First-time setup
    python scripts/google-scholar.py --login-only                   # Refresh session
    python scripts/google-scholar.py --query "transformer"          # Headless search
    python scripts/google-scholar.py --query "LLM" --since 2022 --limit 20
    python scripts/google-scholar.py --status                       # Check cookie age
"""

import argparse
import json
import re
import sys
import time
import random
from datetime import datetime
from pathlib import Path

# Windows GBK stdout fix
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

CONFIG_DIR = Path.home() / ".lit-search-cite"
COOKIE_FILE = CONFIG_DIR / "google_scholar_session.json"
COOKIE_MAX_AGE_DAYS = 7


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

def save_cookies(context, path: Path):
    cookies = context.cookies()
    data = {"cookies": cookies, "saved_at": datetime.now().isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[GS] Cookies saved → {path}", file=sys.stderr)


def load_cookies(path: Path):
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = (datetime.now() - datetime.fromisoformat(data["saved_at"])).days
        if age > COOKIE_MAX_AGE_DAYS:
            print(f"[GS] Warning: cookies are {age} days old (max {COOKIE_MAX_AGE_DAYS}). "
                  "Run --login-only to refresh.", file=sys.stderr)
        return data["cookies"]
    except Exception as e:
        print(f"[GS] Could not load cookies: {e}", file=sys.stderr)
        return None


def cookie_age_days():
    if not COOKIE_FILE.exists():
        return None
    try:
        data = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        return (datetime.now() - datetime.fromisoformat(data["saved_at"])).days
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Browser factory
# ---------------------------------------------------------------------------

def make_context(playwright, headless: bool, cookies=None):
    browser = playwright.chromium.launch(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
    )
    # Mask automation signals
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {} };
    """)
    if cookies:
        context.add_cookies(cookies)
    return browser, context


# ---------------------------------------------------------------------------
# HTML parser
# ---------------------------------------------------------------------------

def parse_results(page) -> list:
    results = []
    try:
        page.wait_for_selector("div#gs_res_ccl_mid", timeout=10_000)
    except Exception:
        return results

    for item in page.query_selector_all("div.gs_r.gs_or"):
        try:
            r = {}

            # Title + URL
            title_el = item.query_selector("h3.gs_rt a")
            if title_el:
                r["title"] = title_el.inner_text().strip()
                r["url"] = title_el.get_attribute("href") or ""
            else:
                h3 = item.query_selector("h3.gs_rt")
                r["title"] = re.sub(r"^\[(CITATION|PDF|HTML)\]\s*", "", h3.inner_text().strip()) if h3 else ""
                r["url"] = ""

            # Authors / year / venue  (format: "A, B - Venue, Year - Publisher")
            meta_el = item.query_selector("div.gs_a")
            if meta_el:
                meta_text = meta_el.inner_text()
                r["meta"] = meta_text
                years = re.findall(r'\b(?:19|20)\d{2}\b', meta_text)
                r["year"] = int(years[0]) if years else None
                parts = meta_text.split(" - ")
                r["authors"] = parts[0].strip() if parts else ""
                r["venue"] = parts[1].strip() if len(parts) > 1 else ""

            # Abstract snippet
            abs_el = item.query_selector("div.gs_rs")
            r["abstract"] = abs_el.inner_text().strip() if abs_el else ""

            # Citation count — try multiple selectors
            cited_by = 0
            for sel in ["div.gs_fl", "div.gs_flb", "div.gs_ri div.gs_fl"]:
                fl_el = item.query_selector(sel)
                if fl_el:
                    m = re.search(r'Cited by (\d[\d,]*)', fl_el.inner_text())
                    if m:
                        cited_by = int(m.group(1).replace(",", ""))
                        break
            r["cited_by"] = cited_by

            results.append(r)
        except Exception:
            continue

    return results


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_setup(args):
    """Open visible browser, let user clear CAPTCHA, save cookies."""
    from playwright.sync_api import sync_playwright

    print("[GS] Opening browser...", file=sys.stderr)
    print("[GS] Steps:", file=sys.stderr)
    print("  1. Google Scholar will open in a real browser window.", file=sys.stderr)
    print("  2. If a CAPTCHA appears, solve it manually.", file=sys.stderr)
    print("  3. Optionally sign in to your Google account.", file=sys.stderr)
    print("  4. Wait until the search page loads normally.", file=sys.stderr)
    print("  5. Press Enter HERE (in this terminal) to save cookies and close the browser.", file=sys.stderr)
    print(file=sys.stderr)

    with sync_playwright() as p:
        browser, context = make_context(p, headless=False, cookies=load_cookies(COOKIE_FILE))
        page = context.new_page()
        page.goto("https://scholar.google.com/", timeout=30_000)

        input("[GS] Press Enter when the page is ready → ")

        save_cookies(context, COOKIE_FILE)
        context.close()
        browser.close()

    print("[GS] Setup complete.", file=sys.stderr)
    print(f"[GS] Session saved to: {COOKIE_FILE}", file=sys.stderr)
    print('[GS] Test search: python scripts/google-scholar.py --query "transformer"')


def cmd_search(args):
    """Headless search using saved cookies."""
    from playwright.sync_api import sync_playwright

    cookies = load_cookies(COOKIE_FILE)
    if not cookies:
        print("[GS] No session found. Running without cookies (CAPTCHA likely).", file=sys.stderr)
        print("[GS] For reliable results run: python scripts/google-scholar.py --setup", file=sys.stderr)

    headless = not getattr(args, "no_headless", False)

    with sync_playwright() as p:
        browser, context = make_context(p, headless=headless, cookies=cookies)
        page = context.new_page()

        # Build URL
        q = args.query.replace(" ", "+")
        url = f"https://scholar.google.com/scholar?q={q}&hl=en"
        if args.since:
            url += f"&as_ylo={args.since}"
        if args.until:
            url += f"&as_yhi={args.until}"

        print(f"[GS] GET {url}", file=sys.stderr)
        page.goto(url, timeout=30_000)

        # CAPTCHA / block detection
        blocked = (
            "sorry" in page.url.lower()
            or page.query_selector("form#captcha-form") is not None
            or page.query_selector("div#recaptcha") is not None
        )
        if blocked:
            print("[GS] CAPTCHA detected — cookies expired.", file=sys.stderr)
            print("[GS] Refresh session: python scripts/google-scholar.py --login-only", file=sys.stderr)
            context.close()
            browser.close()
            sys.exit(1)

        all_results = []
        page_num = 0

        while len(all_results) < args.limit and page_num < 5:
            page_num += 1
            batch = parse_results(page)
            if not batch:
                break
            all_results.extend(batch)

            if len(all_results) >= args.limit:
                break

            # Next page
            next_btn = (
                page.query_selector("button.gs_btnPR")
                or page.query_selector("td.gs_btnPR")
            )
            if not next_btn:
                break
            next_btn.click()
            # Small human-like delay
            time.sleep(random.uniform(1.5, 3.0))

        # Persist fresh cookies
        save_cookies(context, COOKIE_FILE)
        context.close()
        browser.close()

    output = {
        "query": args.query,
        "url": url,
        "count": len(all_results[:args.limit]),
        "results": all_results[:args.limit],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def cmd_status(_args):
    age = cookie_age_days()
    if age is None:
        print("Status: NOT SET UP")
        print("Run:    python scripts/google-scholar.py --setup")
    elif age > COOKIE_MAX_AGE_DAYS:
        print(f"Status: STALE ({age}d old, max {COOKIE_MAX_AGE_DAYS}d)")
        print("Run:    python scripts/google-scholar.py --login-only")
    else:
        print(f"Status: READY (cookies {age}d old)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Google Scholar via Playwright — headless after one-time setup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/google-scholar.py --setup
  python scripts/google-scholar.py --query "attention is all you need" --limit 10
  python scripts/google-scholar.py --query "diffusion models" --since 2022 --limit 20
  python scripts/google-scholar.py --login-only
  python scripts/google-scholar.py --status
        """,
    )
    parser.add_argument("--query", "-q", help="Search query")
    parser.add_argument("--limit", "-n", type=int, default=10, help="Max results (default: 10)")
    parser.add_argument("--since", type=int, help="Year range start")
    parser.add_argument("--until", type=int, help="Year range end")
    parser.add_argument("--setup", action="store_true", help="First-time setup (opens visible browser)")
    parser.add_argument("--login-only", dest="login_only", action="store_true",
                        help="Refresh session cookies (alias for --setup)")
    parser.add_argument("--status", action="store_true", help="Show cookie age and readiness")
    parser.add_argument("--no-headless", dest="no_headless", action="store_true",
                        help="Show browser window during search (for debugging)")

    args = parser.parse_args()

    if args.setup or args.login_only:
        cmd_setup(args)
    elif args.status:
        cmd_status(args)
    elif args.query:
        cmd_search(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Automates Vulcan UONET+ credential refresh via web scraping.

Logs into the Vulcan portal, navigates to mobile device registration,
generates a new access code (token/PIN), then uses vulcan-api to
register a new device and save account.json and keystore.json.

Usage:
    source .venv/bin/activate
    python scripts/refresh_credentials.py

Credentials (in order of priority):
    1. Environment variables: VULCAN_USERNAME, VULCAN_PASSWORD, VULCAN_URL
    2. vulcan-creds.txt in project root (username/password/url, one per line)

Requirements (install in .venv):
    pip install playwright vulcan-api
    playwright install chromium
"""

import asyncio
import os
import re
import sys

from pathlib import Path
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# School unit ID - found in the Uczeń URL path
SCHOOL_UNIT_ID = "002085"


def load_credentials():
    """Load credentials from env vars or vulcan-creds.txt."""
    username = os.environ.get("VULCAN_USERNAME")
    password = os.environ.get("VULCAN_PASSWORD")
    url = os.environ.get("VULCAN_URL")

    if not all([username, password, url]):
        creds_file = PROJECT_ROOT / "vulcan-creds.txt"
        if creds_file.exists():
            lines = creds_file.read_text().strip().splitlines()
            if len(lines) >= 3:
                username = username or lines[0].strip()
                password = password or lines[1].strip()
                url = url or lines[2].strip()

    if not all([username, password, url]):
        print("Error: Missing credentials.")
        print("Set VULCAN_USERNAME, VULCAN_PASSWORD, VULCAN_URL env vars")
        print("or create vulcan-creds.txt with username/password/url on separate lines.")
        sys.exit(1)

    return username, password, url


def extract_symbol(url):
    """Extract symbol from portal URL (e.g. 'torun' from https://uonetplus.vulcan.net.pl/torun)."""
    return url.rstrip("/").split("/")[-1]


def login_and_get_token(username, password, portal_url):
    """
    Log into Vulcan portal, navigate to mobile access in the Uczeń SPA,
    generate a new access code, and extract token + PIN + symbol.
    """
    symbol = extract_symbol(portal_url)
    uczen_url = f"https://uonetplus-uczen.vulcan.net.pl/{symbol}/{SCHOOL_UNIT_ID}/App"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Step 1: Login via ADFS Light
        print(f"Navigating to {portal_url}...")
        page.goto(portal_url, wait_until="networkidle")
        page.wait_for_timeout(2000)
        print(f"Login page: {page.url}")

        page.fill("#Username", username)
        page.fill("#Password", password)
        page.click('button:has-text("ZALOGUJ")')
        page.wait_for_timeout(5000)

        # Verify login succeeded (should redirect away from login page)
        if "LoginPage" in page.url:
            error_el = page.query_selector(".validation-summary-errors, .error-message")
            error_msg = error_el.inner_text() if error_el else "Unknown error"
            print(f"Login failed: {error_msg}")
            sys.exit(1)

        print(f"Logged in successfully. Dashboard: {page.url}")

        # Step 2: Navigate to Uczeń SPA
        print(f"Navigating to Uczeń app: {uczen_url}")
        page.goto(uczen_url, wait_until="networkidle")
        page.wait_for_timeout(3000)

        # Step 3: Navigate to Dostęp mobilny > Urządzenia mobilne
        print("Opening 'Dostęp mobilny'...")
        page.click('button:has-text("Dostęp mobilny")')
        page.wait_for_timeout(1000)

        print("Opening 'Urządzenia mobilne'...")
        page.click('button:has-text("Urządzenia mobilne")')
        page.wait_for_timeout(2000)

        # Step 4: Click "Wygeneruj kod dostępu" to generate new token
        print("Generating new access code...")
        page.click('button:has-text("Wygeneruj kod dostępu")')
        page.wait_for_timeout(3000)

        # Step 5: Extract Token and PIN from page text
        page_text = page.inner_text("body")

        token_match = re.search(r"Token:\s*(\S+)", page_text)
        pin_match = re.search(r"PIN:\s*(\d+)", page_text)
        symbol_match = re.search(r"Symbol:\s*(\S+)", page_text)

        browser.close()

        if not token_match or not pin_match:
            print("Failed to extract token/PIN from page.")
            print(f"Page text:\n{page_text[:2000]}")
            sys.exit(1)

        token = token_match.group(1)
        pin = pin_match.group(1)
        if symbol_match:
            symbol = symbol_match.group(1)

        print(f"  Token:  {token}")
        print(f"  Symbol: {symbol}")
        print(f"  PIN:    {pin}")

        return token, pin, symbol


async def register_device(token, pin, symbol):
    """Register a new device using vulcan-api and save credentials."""
    from vulcan import Account, Keystore

    print("\nRegistering device with vulcan-api...")

    keystore = await Keystore.create(device_model="Vulcan API")
    keystore_path = PROJECT_ROOT / "keystore.json"
    with open(keystore_path, "w") as f:
        f.write(keystore.as_json)
    print(f"  Saved {keystore_path}")

    account = await Account.register(keystore, token, symbol, pin)
    account_path = PROJECT_ROOT / "account.json"
    with open(account_path, "w") as f:
        f.write(account.as_json)
    print(f"  Saved {account_path}")

    print("\nDone! New credentials saved locally.")
    print("Update GitHub secrets with the contents of:")
    print(f"  VULCAN_KEYSTORE_JSON <- {keystore_path}")
    print(f"  VULCAN_ACCOUNT_JSON  <- {account_path}")


def main():
    username, password, portal_url = load_credentials()
    print(f"Username: {username}")
    print(f"URL:      {portal_url}")

    token, pin, symbol = login_and_get_token(username, password, portal_url)
    asyncio.run(register_device(token, pin, symbol))


if __name__ == "__main__":
    main()

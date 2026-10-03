"""
Objective 1 - Disney Cruise Line scraper
----------------------------------------
Steps (as per the challenge document):
  1. Open https://disneycruise.disney.go.com/en-in/
  2. Choose filters programmatically and click "View Dates"
  3. Wait until the cruise cards load
  4. Scroll to the end of the page (infinite scroll) and collect every card
     -> all 35 pages (5 cards per page)
  5. Clean the data (no empty fields, no duplicates, location present)
  6. Save results.csv and print answers to the analysis questions

Two extra filtered searches are run with the site's own filters so the
answers use Disney's classification instead of guessing from titles:
  - "Themed or Holiday" -> Halloween on the High Seas + Very Merrytime
  - "Sailing to"        -> Pacific Coast Cruises

Run:
  pip install playwright pandas
  python -m playwright install chromium
  python disney_cruise_scraper.py

Note: Disney blocks headless browsers ("Access Denied"), so the browser runs
with a visible window (HEADLESS = False).
"""

import json
import time

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

HOME_URL = "https://disneycruise.disney.go.com/en-in/"
HEADLESS = False
MIN_PAGES = 35                 # the challenge asks for at least 35 pages
RAW_FILE = "disney_raw.json"   # temporary (uncleaned) data
OUTPUT_FILE = "results.csv"    # final cleaned data

# Filters are (tab in the search bar, option label shown on the site)
MAIN_FILTERS = []  # no restriction -> every cruise (35 pages)
HOLIDAY_FILTERS = [("more-filters", "Halloween on the High Seas"),
                   ("more-filters", "Very Merrytime")]
PACIFIC_FILTERS = [("destination", "Pacific Coast Cruises")]

# JavaScript that reads every cruise card currently in the DOM.
EXTRACT_CARDS_JS = r"""
() => [...document.querySelectorAll('.product-card-primary-wrapper')].map(card => {
  const txt = sel => (card.querySelector(sel)?.innerText || '').trim();
  // The chip label also contains hidden tooltip text; keep only its own text.
  const chip = card.querySelector('.chip-label');
  const offer = chip ? (chip.childNodes[0]?.textContent || '').trim() : '';
  // The USD price is inside the <wdpr-price> web component (shadow DOM).
  const wp = card.querySelector('wdpr-price');
  const usd = wp ? (wp.shadowRoot?.textContent || wp.textContent || '') : '';
  const ports = [...card.querySelectorAll('.product-card-content__sailing-to li, .product-card-content__sailing-to span')]
      .map(e => e.innerText.trim()).filter(Boolean);
  return {
    title:        txt('.product-card-content__name'),
    offer:        offer,
    sailing_to:   [...new Set(ports)].join(' | ') || txt('.product-card-content__sailing-to'),
    price_usd:    usd.trim(),
    price_inr:    txt('.wrapper-price__pricing'),
    guests:       txt('.total-guests-number__guests-label'),
    dates_button: txt('.product-card-footer-wrapper__btn'),
  };
})
"""


def accept_cookies(page):
    """Click the OneTrust cookie banner if it shows up."""
    try:
        page.click("#onetrust-accept-btn-handler", timeout=3000)
    except PWTimeout:
        pass  # banner did not appear


def apply_filter(page, tab, label):
    """Open a search-bar tab and tick one option (image tile or checkbox)."""
    option = page.locator(
        f'button.image-picker-item[aria-label*="{label}"], [role=checkbox][aria-label="{label}"]'
    ).first
    if not option.is_visible():  # clicking an open tab again would close it
        page.click(f"li.filter-option-{tab}")
    option.wait_for(timeout=15000)
    try:
        option.click(timeout=5000)
    except PWTimeout:  # another element overlaps the tile -> click via JavaScript
        option.evaluate("el => el.click()")
    page.wait_for_timeout(1000)


def run_search(page, filters, label):
    """Open the home page, apply filters, click View Dates, scroll and collect cards."""
    cards = {}            # dedupe key -> card (cards may be recycled by virtual scroll)
    pages_loaded = set()  # page numbers returned by the site's API while scrolling
    total_pages = [None]

    def on_response(resp):
        if "available-products" in resp.url and resp.request.method == "POST":
            try:
                pages_loaded.add(json.loads(resp.request.post_data or "{}").get("page"))
                total_pages[0] = resp.json().get("totalPages")
            except Exception:
                pass

    page.on("response", on_response)

    # Step 1: navigate and agree
    page.goto(HOME_URL, timeout=90000)
    page.wait_for_selector("li.filter-option-destination", timeout=60000)
    page.wait_for_timeout(3000)
    accept_cookies(page)

    # Step 2: choose filters and click "View Dates"
    for tab, option in filters:
        apply_filter(page, tab, option)
    page.get_by_role("button", name="View Dates").first.click()

    # Step 3: wait for the result cards
    page.wait_for_selector(".product-card-primary-wrapper", timeout=90000)
    page.wait_for_timeout(3000)
    accept_cookies(page)

    # Step 4: keep scrolling to the end until no new cards arrive
    idle_rounds = 0
    while idle_rounds < 5:
        before = len(cards)
        for c in page.evaluate(EXTRACT_CARDS_JS):
            if c["title"] and c["price_inr"]:  # skip cards still rendering
                cards[json.dumps(c, sort_keys=True)] = c
        page.mouse.wheel(0, 4000)
        page.keyboard.press("End")
        page.wait_for_timeout(2500)
        all_pages = total_pages[0] and len(pages_loaded) >= total_pages[0]
        idle_rounds = idle_rounds + 1 if (len(cards) == before or all_pages) else 0
        print(f"[{label}] cards: {len(cards):4d} | pages loaded: {len(pages_loaded)}/{total_pages[0]}")

    page.context.close()
    return list(cards.values()), len(pages_loaded)


def scrape():
    """Run the main search plus the two filtered searches in one browser."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS, args=["--disable-blink-features=AutomationControlled"]
        )
        # A fresh context per search so filters from one search never leak into the next
        new_page = lambda: browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
        all_cards, pages = run_search(new_page(), MAIN_FILTERS, "all")
        holiday_cards, _ = run_search(new_page(), HOLIDAY_FILTERS, "holiday")
        pacific_cards, _ = run_search(new_page(), PACIFIC_FILTERS, "pacific")
        browser.close()

    if pages < MIN_PAGES:
        print(f"WARNING: only {pages} pages loaded (expected >= {MIN_PAGES})")
    return {"all": all_cards, "holiday": holiday_cards, "pacific": pacific_cards}


def card_key(c):
    """Identity of a card: same title, route and price = same cruise card."""
    return (c["title"], c["sailing_to"], c["price_inr"])


def clean(raw):
    """Step 5: tidy text, split columns, drop empties and duplicates."""
    df = pd.DataFrame(raw["all"])
    df = df.apply(lambda col: col.str.replace(r"\s+", " ", regex=True).str.strip())

    # Tag cards found by the site's own Holiday / Pacific Coast filters
    holiday = {card_key(c) for c in raw["holiday"]}
    pacific = {card_key(c) for c in raw["pacific"]}
    keys = list(zip(df["title"], df["sailing_to"], df["price_inr"]))
    df["Holiday Cruise"] = ["Yes" if k in holiday else "No" for k in keys]
    df["Pacific Coast"] = ["Yes" if k in pacific else "No" for k in keys]

    # Title looks like "7-Night Alaskan Cruise from Vancouver ending in San Diego"
    parts = df["title"].str.extract(
        r"^(?P<nights>\d+)-Night .*? from (?P<dep>.+?)(?: ending(?: in)? (?P<end>.+?))?(?: with .*)?$"
    )
    df["Nights"] = parts["nights"]
    df["Departing From"] = parts["dep"]
    df["Ending In"] = parts["end"].fillna(parts["dep"])  # round trip -> same port

    # "1142 USD$1,14250USDUSD" -> "$1,142" (the first number is the visible price)
    df["price_usd"] = (df["price_usd"].str.extract(r"^(\d+)", expand=False)
                       .astype(float).map(lambda v: f"${v:,.0f}"))
    df["Number of Dates"] = df["dates_button"].str.extract(r"(\d+)", expand=False).astype("Int64")

    # A card with no "Sailing to" list (e.g. Singapore round trip) visits its home port
    df["sailing_to"] = df["sailing_to"].replace("", pd.NA).fillna(df["Departing From"])
    df["offer"] = df["offer"].replace("", "No Special Offer")

    df = df.rename(columns={
        "title": "Cruise Name", "offer": "Offer", "sailing_to": "Sailing To",
        "price_usd": "Price From (USD)", "price_inr": "Price From (INR)", "guests": "Guests",
    })
    columns = ["Cruise Name", "Nights", "Departing From", "Ending In", "Sailing To", "Offer",
               "Price From (USD)", "Price From (INR)", "Guests", "Number of Dates",
               "Holiday Cruise", "Pacific Coast"]
    df = df[columns].replace("", pd.NA).dropna()       # no empty fields
    return df.drop_duplicates().reset_index(drop=True)  # no duplicate rows


def answer_questions(df):
    """Print the answers required by the challenge."""
    dep = df["Departing From"]
    print("\n================ ANSWERS ================")
    print("(i)   Cruises with Pacific as destination :", (df["Pacific Coast"] == "Yes").sum())
    print("(ii)  Total cruises                       :", len(df))
    print("(iii) Holiday cruises                     :", (df["Holiday Cruise"] == "Yes").sum())
    print("(iv)  Cruises with more than 2 dates      :", (df["Number of Dates"] > 2).sum())
    print("(v)   Departing from Miami                :", dep.str.contains("Miami").sum())
    print("      Departing from London               :", dep.str.contains("London").sum())
    print("      (London's cruise port is Southampton:", dep.str.contains("Southampton").sum(), ")")


def main():
    start = time.time()
    raw = scrape()
    with open(RAW_FILE, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, ensure_ascii=False)
    print(f"Saved raw cards -> {RAW_FILE}")

    df = clean(raw)
    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    print(f"Saved {len(df)} clean rows -> {OUTPUT_FILE}  ({time.time() - start:.0f}s)")
    answer_questions(df)


if __name__ == "__main__":
    main()

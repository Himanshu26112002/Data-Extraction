"""
Objective 2 - IngredientsNetwork.com scraper
--------------------------------------------
Steps (as per the challenge document):
  1. Open https://www.ingredientsnetwork.com/
  2. Click the Search button
  3. Wait for the results and extract data from all cards
     - the results page loads one JSON index (search46json.jsp) holding every
       card (companies + products) and which filters each card belongs to
     - every COMPANY card is then opened to read the required fields
  4. Save the raw data to a temporary CSV, clean it
  5. Save the cleaned data to ingredients_results.csv and print the answers

Run:
  pip install playwright pandas requests beautifulsoup4
  python -m playwright install chromium
  python ingredients_network_scraper.py
"""

import html
import json
import re
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

HOME_URL = "https://www.ingredientsnetwork.com/"
BASE_URL = "https://www.ingredientsnetwork.com"
RAW_FILE = "ingredients_raw.csv"          # temporary (uncleaned) data
OUTPUT_FILE = "ingredients_results.csv"   # final cleaned data
ANSWERS_FILE = "ingredients_answers.json" # answers, also shown by the web app
DELAY = 1.0                               # seconds between page requests (be polite)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}


# ---------------------------------------------------------------- step 1-3a
def get_search_index():
    """Open the site, click Search and capture the JSON behind the result cards."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        page.goto(HOME_URL, timeout=90000)
        try:
            page.get_by_role("button", name="Accept all").click(timeout=5000)
        except PWTimeout:
            pass  # no cookie banner

        # Step 2: click Search; Step 3: wait for the search index + cards
        with page.expect_response(lambda r: "search46json.jsp" in r.url, timeout=90000) as resp:
            page.click("button.hero-search__button")
        index = json.loads(resp.value.text())
        page.wait_for_selector("text=Read more", timeout=60000)
        print(f"Search results loaded: {len(index['results'])} cards")
        browser.close()
    return index


def facet_lookup(index):
    """Map each filter value to (facet title, name, indent level)."""
    lookup = {}
    for facet in index["facets"]:
        for f in facet["filters"]:
            name = html.unescape(f["name"])
            level = (len(name) - len(name.lstrip("\xa0"))) // 3  # 3 nbsp per level
            lookup[f["value"]] = (html.unescape(facet["title"]), name.strip(), level)
    return lookup


def subtree(lookup, facet, name):
    """Filter values for a category plus all of its sub-categories."""
    values = sorted(v for v, (fc, _, _) in lookup.items() if fc == facet)
    start = next(v for v in values if lookup[v][1] == name)
    level, result = lookup[start][2], [start]
    for v in values[values.index(start) + 1:]:
        if lookup[v][2] <= level:
            break
        result.append(v)
    return result


def has_any(card, values):
    """True if the card is tagged with any of the given filter values."""
    return any(card["filterVal"][v] == "1" for v in values)


# ---------------------------------------------------------------- step 3b
def decode_cf_email(encoded):
    """Cloudflare shows emails as hex XOR-ed with the first byte; decode it."""
    key = int(encoded[:2], 16)
    return "".join(chr(int(encoded[i:i + 2], 16) ^ key) for i in range(2, len(encoded), 2))


def text(el):
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""


def parse_company(page_html, url):
    """Read the required fields from one company page."""
    s = BeautifulSoup(page_html, "html.parser")

    desc_head = s.find("h3", string=re.compile(r"Company description"))
    quick = {text(tr.th).rstrip(":"): text(tr.td) for tr in s.select("table.quickfacts tr") if tr.th}

    # Full category list: "Parent: child, child; Parent2: ..."
    categories = []
    for block in s.select(".company-categories .category"):
        parent = text(block.find("a"))
        children = [text(a) for a in block.select(".subcategories a")]
        categories.append(f"{parent}: {', '.join(children)}" if children else parent)

    # Events listed under the "Upcoming events" heading (not "Recently at")
    events = []
    head = s.find("h2", string=re.compile(r"Upcoming events"))
    for sib in (head.find_next_siblings() if head else []):
        if sib.name == "h2":
            break
        if "event" in (sib.get("class") or []):
            events.append(text(sib.find("h3")))

    # Contact details sit in the hidden "company-information" popup
    info = s.find(id="company-information") or s
    def after(label):
        h = info.find("h3", string=re.compile(rf"^\s*{label}\s*$"))
        return h.find_next_sibling() if h else None

    email_el = after("Email")
    cf = email_el.select_one("[data-cfemail]") if email_el else None
    email = decode_cf_email(cf["data-cfemail"]) if cf else text(email_el)

    return {
        "Company Name": text(s.find("h1")),
        "Company Description": text(desc_head.find_next_sibling("p")) if desc_head else "",
        "Sales Markets": quick.get("Sales markets", ""),
        "Primary Business Activity": quick.get("Primary business activity", ""),
        "Categories": "; ".join(categories) or quick.get("Affiliated categories", ""),
        "Events": "; ".join(events),
        "Address": text(after("Address")),
        "Email": email,
        "Telephone": text(after("Telephone")),
        "Website": text(after("Website")),
        "Profile URL": url,
    }


def company_url(card):
    """Card JSON lives at /47/company/31/69/51/search316951_46.json -> gives the page link."""
    cid = str(card["id"])
    path = f"{cid[:-4]}/{cid[-4:-2]}/{cid[-2:]}"
    meta = requests.get(f"{BASE_URL}/47/company/{path}/search{cid}_46.json?v=21",
                        headers=HEADERS, timeout=30).json()["result"]
    return meta["link"]


def scrape_companies(companies):
    rows = []
    session = requests.Session()
    session.headers.update(HEADERS)
    for i, card in enumerate(companies, 1):
        try:
            url = company_url(card)
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            row = parse_company(resp.text, url)
            row["Company ID"] = card["id"]
            rows.append(row)
            print(f"[{i}/{len(companies)}] {row['Company Name']}")
        except Exception as e:  # keep going if one page fails
            print(f"[{i}/{len(companies)}] FAILED id={card['id']}: {e}")
        time.sleep(DELAY)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- step 4
def clean(df):
    """Trim text, validate email/website, fill gaps and drop duplicates.

    Some companies simply do not publish a field (e.g. no telephone or no
    upcoming events). Dropping them would lose ~60% of real companies, so a
    missing value is written as "Not Available" instead of left empty.
    Rows without a company name are dropped.
    """
    required = ["Company Name", "Company Description", "Sales Markets",
                "Primary Business Activity", "Categories", "Events",
                "Address", "Email", "Telephone", "Website"]
    df = df.copy()
    for col in required:
        df[col] = df[col].fillna("").astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    df["Email"] = df["Email"].where(df["Email"].str.contains(r"^[^@\s]+@[^@\s]+\.\w+$"), "")
    df["Website"] = df["Website"].where(df["Website"].str.startswith("http"), "")

    df = df[df["Company Name"] != ""]
    gaps = df[required].eq("").sum()
    if gaps.any():
        print("Fields not published by some companies (filled with 'Not Available'):")
        print(gaps[gaps > 0].to_string())
    df[required] = df[required].replace("", "Not Available")
    df = df.drop_duplicates(subset=["Company ID"]).drop_duplicates(subset=required)
    return df[["Company ID"] + required + ["Profile URL"]].reset_index(drop=True)


# ---------------------------------------------------------------- step 5
def answer_questions(index, df):
    lookup = facet_lookup(index)
    cards = index["results"]
    products = [c for c in cards if c["type"] == "product"]
    companies = [c for c in cards if c["type"] == "company" and c["id"] in set(df["Company ID"])]

    ingredients = [v for v, (fc, _, _) in lookup.items() if fc == "Ingredients"]
    finished = [v for v, (fc, _, _) in lookup.items() if fc == "Finished Products"]
    herbs = subtree(lookup, "Ingredients", "Herbs, Spices")
    physical = subtree(lookup, "Delivery Formats", "Physical Formats")
    cognitive = subtree(lookup, "Health & Wellness", "Cognitive & Mental Health")
    count = lambda items, vals: sum(has_any(c, vals) for c in items)

    answers = [
        ("(i)", "Total ingredients (products)", count(products, ingredients)),
        ("(ii)", "Total finished products", count(products, finished)),
        ("(iii)", "Companies with Herbs, Spices", count(companies, herbs)),
        ("(iv)", "Companies with Physical delivery formats", count(companies, physical)),
        ("(v)", "Companies in Cognitive & Mental Health", count(companies, cognitive)),
    ]
    print("\n================ ANSWERS ================")
    for num, question, value in answers:
        print(f"{num:6}{question:42}: {value}")
    print(f"(based on {len(products)} product cards and {len(companies)} clean companies)")

    # Saved for the web app, which only has the CSV and not the filter categories
    with open(ANSWERS_FILE, "w", encoding="utf-8") as f:
        json.dump([{"question": q, "answer": v} for _, q, v in answers], f, indent=2)


def main():
    index = get_search_index()
    company_cards = [c for c in index["results"] if c["type"] == "company"]
    print(f"{len(company_cards)} company cards, "
          f"{len(index['results']) - len(company_cards)} product cards")

    raw = scrape_companies(company_cards)
    raw.to_csv(RAW_FILE, index=False, encoding="utf-8-sig")
    print(f"Saved {len(raw)} raw rows -> {RAW_FILE}")

    df = clean(raw)
    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    print(f"Saved {len(df)} clean rows -> {OUTPUT_FILE}")
    answer_questions(index, df)


if __name__ == "__main__":
    main()

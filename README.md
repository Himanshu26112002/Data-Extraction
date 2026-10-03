# Relu Consultancy – Data Extraction Challenge

Two web scrapers plus a small web app that shows the scraped data.

| Part | Source | Script | Output |
|---|---|---|---|
| Objective 1 | disneycruise.disney.go.com | `disney_cruise_scraper.py` | `results.csv` (171 cruises) |
| Objective 2 | ingredientsnetwork.com | `ingredients_network_scraper.py` | `ingredients_results.csv` (185 companies) |
| Bonus | – | `webapp/` (FastAPI) | live tables + JSON API |

## Project structure

```
relu/
├── disney_cruise_scraper.py        # Objective 1
├── ingredients_network_scraper.py  # Objective 2
├── results.csv                     # Objective 1 output
├── ingredients_results.csv         # Objective 2 output
├── ingredients_answers.json        # Objective 2 answers (used by the web app)
├── requirements.txt                # scraper dependencies
└── webapp/                         # Bonus web app
    ├── main.py
    ├── templates/                  # base, index, table pages
    ├── data/                       # copies of the two CSVs
    ├── requirements.txt
    └── railway.json                # Railway start command + health check
```

## Setup

Python 3.11+ is required.

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## Objective 1 – Disney Cruise Line

```bash
python disney_cruise_scraper.py
```

How it works:

1. Opens the `en-in` home page and accepts cookies.
2. Clicks **View Dates** with no departure filter. This search returns the required 35 pages.
3. Waits for the cruise cards, then scrolls to the end of the page. Cards are collected on every scroll step because the list removes cards that are off screen.
4. Runs two more searches with the site's own filters. Rows that appear in these searches are tagged in the CSV:
   - *Themed or Holiday* → *Halloween on the High Seas* + *Very Merrytime*
   - *Sailing to* → *Pacific Coast Cruises*
5. Saves raw data to `disney_raw.json`, cleans it and writes `results.csv`.
6. Prints the answers in the terminal.

Cleaning rules:

- Whitespace is trimmed.
- Hidden tooltip and screen-reader text is removed.
- Nights, departure port and end port are taken from the title.
- Cards with no "Sailing to" list use their home port as the location.
- There are no empty cells and no duplicate rows.

> Disney blocks headless browsers ("Access Denied"), so this script opens a
> visible Chrome window. Run it on a desktop machine, not in Colab.

**Columns:** Cruise Name, Nights, Departing From, Ending In, Sailing To, Offer,
Price From (USD), Price From (INR), Guests, Number of Dates, Holiday Cruise, Pacific Coast

## Objective 2 – IngredientsNetwork

```bash
python ingredients_network_scraper.py
```

How it works:

1. Opens the home page and clicks **Search**.
2. Captures the JSON index the results page loads. It holds all 3,962 cards (185 companies + 3,777 products) and the filter categories of each card.
3. Opens every company page, one request per second, and reads the 10 required fields. The email is decoded from Cloudflare's email protection.
4. Saves raw data to `ingredients_raw.csv`, cleans it and writes `ingredients_results.csv`.
5. Prints the answers and saves them to `ingredients_answers.json`. They are counted with the same filter categories the site uses.

Cleaning rules:

- Whitespace is trimmed.
- Emails and websites are validated.
- Duplicates are removed by company ID.
- Some companies do not publish every field. For example, 61 have no telephone number. These companies are kept, and the missing value is written as `Not Available`, so no cell is empty.

**Columns:** Company ID, Company Name, Company Description, Sales Markets,
Primary Business Activity, Categories, Events, Address, Email, Telephone, Website, Profile URL

## Answers

Disney Cruise Line:

| Question | Answer |
|---|---|
| (i) Cruises with Pacific as destination | 2 |
| (ii) Total cruises | 171 |
| (iii) Holiday cruises | 71 |
| (iv) Cruises with more than 2 dates | 67 |
| (v) Cruises departing from Miami / London | 0 / 0 |

For (v): neither city is a Disney departure port. The nearest port to London is Southampton, with 10 cruises.

IngredientsNetwork:

| Question | Answer |
|---|---|
| (i) Total ingredients | 2,575 |
| (ii) Total finished products | 766 |
| (iii) Companies with herbs and spices | 22 |
| (iv) Companies with physical delivery formats | 55 |
| (v) Companies in Cognitive & Mental Health | 47 |

Both sites change daily, so a re-run can give slightly different numbers.

## Bonus – Web app (FastAPI)

### Run locally

```bash
cd webapp
pip install -r requirements.txt
python -m uvicorn main:app --reload
```

Open http://127.0.0.1:8000

| Route | Shows |
|---|---|
| `/` | Overview: record counts + answers for both objectives |
| `/cruises` | Disney cruises table with search |
| `/ingredients` | IngredientsNetwork companies table with search |
| `/api/cruises` | Cruises as JSON |
| `/api/ingredients` | Companies as JSON |
| `/health` | Health check (`{"status": "ok"}`) |
| `/docs` | Interactive API docs (generated by FastAPI) |

### Update the data

After re-running the scrapers, copy the new output into the app:

```bash
cp results.csv webapp/data/cruises.csv
cp ingredients_results.csv webapp/data/ingredients.csv
cp ingredients_answers.json webapp/data/ingredients_answers.json
```

The Disney answers are calculated from the CSV. The IngredientsNetwork answers depend on the
site's filter categories, which are not in the CSV, so they are read from
`ingredients_answers.json`, which the scraper writes.

### Deploy on Railway

1. Push this repository to GitHub.
2. On [railway.com](https://railway.com), choose **New Project → Deploy from GitHub repo** and select it.
3. Under **Settings → Root Directory**, enter `/webapp`.
4. Under **Settings → Networking**, click **Generate Domain** to get the public URL.

`webapp/railway.json` sets the start command
(`uvicorn main:app --host 0.0.0.0 --port $PORT`) and the `/health` check.

### Deploy on Replit

1. On [replit.com](https://replit.com), choose **Create App → Import from GitHub** and paste the repository URL.
2. Click **Run** to test. The `.replit` file installs `webapp/requirements.txt` and starts the server on port 8080.
3. Click **Deploy** and choose **Autoscale**. The live `*.replit.app` URL appears when the deployment finishes.

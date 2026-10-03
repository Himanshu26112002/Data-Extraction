"""
Web app for the scraped challenge data.

Pages:
  /             summary + answers to the challenge questions
  /cruises      Disney Cruise Line table (results.csv)
  /ingredients  IngredientsNetwork companies table (ingredients_results.csv)
  /api/...      the same data as JSON

Run locally:
  pip install -r requirements.txt
  uvicorn main:app --reload
"""

import json
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

app = FastAPI(title="Relu Scraping Challenge")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def load(name):
    """Read a CSV as plain strings so values show exactly as scraped."""
    return pd.read_csv(DATA_DIR / name, dtype=str, keep_default_na=False)


cruises = load("cruises.csv")
companies = load("ingredients.csv").drop(columns=["Company ID"])

# Written by ingredients_network_scraper.py (needs the site's filter data, not just the CSV)
ingredient_answers = json.loads((DATA_DIR / "ingredients_answers.json").read_text(encoding="utf-8"))


def cruise_answers():
    dates = cruises["Number of Dates"].astype(int)
    port = cruises["Departing From"]
    return [
        ("Cruises with Pacific as destination", int((cruises["Pacific Coast"] == "Yes").sum())),
        ("Total cruises", len(cruises)),
        ("Holiday cruises", int((cruises["Holiday Cruise"] == "Yes").sum())),
        ("Cruises with more than 2 dates", int((dates > 2).sum())),
        ("Departing from Miami / London", f"{port.str.contains('Miami').sum()} / "
                                          f"{port.str.contains('London').sum()}"),
    ]


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "cruise_count": len(cruises),
        "company_count": len(companies),
        "cruise_answers": cruise_answers(),
        "ingredient_answers": [(a["question"], a["answer"]) for a in ingredient_answers],
    })


@app.get("/cruises")
def cruises_page(request: Request):
    return templates.TemplateResponse(request, "table.html", {
        "title": "Disney Cruise Line", "active": "cruises",
        "columns": list(cruises.columns), "rows": cruises.values.tolist(),
    })


@app.get("/ingredients")
def ingredients_page(request: Request):
    return templates.TemplateResponse(request, "table.html", {
        "title": "IngredientsNetwork Companies", "active": "ingredients",
        "columns": list(companies.columns), "rows": companies.values.tolist(),
    })


@app.get("/api/cruises")
def cruises_api():
    return cruises.to_dict(orient="records")


@app.get("/api/ingredients")
def ingredients_api():
    return companies.to_dict(orient="records")


@app.get("/health")
def health():
    return {"status": "ok"}

import argparse
import json
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd

DEFAULT_BASE_URL = "https://directory.lunch-check.ch/"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
REQUEST_TIMEOUT = 120

# Same columns as the former Selenium scraper, so merge_datasets.py is unaffected.
# The new directory API does not expose a phone number, so that column stays empty.
# Latitude/Longitude are new: they allow matching hotels to restaurants by location.
OUTPUT_COLUMNS = ["Restaurant Name", "Address", "ZIP Code", "City", "Canton", "Phone", "Latitude", "Longitude"]


def http_json(url, payload=None, origin=None):
    """GET (or POST when payload is given) a URL and return the decoded JSON body."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if origin:
        headers["Origin"] = origin
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def get_backend_url(base_url):
    """
    The directory is a Blazor WebAssembly app; the URL of its REST backend is published in
    appsettings.json next to the app. Reading it avoids hardcoding an Azure hostname.
    """
    settings = http_json(urljoin(base_url, "appsettings.json"))
    return settings["BackendConfig"]["RestaurantDirectoryHttpUrl"].rstrip("/")


def fetch_restaurants(base_url):
    """Fetches every accepted restaurant in a single search request (no filters, no paging)."""
    backend_url = get_backend_url(base_url)
    print(f"Using backend {backend_url}")

    payload = {
        "queryCriteria": {},
        "cuisineTypeFilter": [],
        "serviceFilters": [],
        "restrictions": [],
    }
    result = http_json(f"{backend_url}/restaurants/search", payload=payload, origin=base_url.rstrip("/"))

    paged = result["restaurantsPaged"]
    if paged.get("pageCount", 1) != 1:
        raise RuntimeError(f"Expected all restaurants in one page, got pageCount={paged['pageCount']}.")
    items = paged["items"]

    expected = result.get("totalCount")
    if expected is not None and expected != len(items):
        raise RuntimeError(f"Search returned {len(items)} restaurants but totalCount is {expected}.")
    return items


def to_dataframe(items):
    rows = [
        {
            "Restaurant Name": (item.get("name") or item.get("displayName") or "").strip(),
            "Address": (item.get("address") or "").strip(),
            "ZIP Code": (item.get("zip") or "").strip(),
            "City": (item.get("city") or "").strip(),
            "Canton": (item.get("region") or "").strip(),
            "Phone": "",
            "Latitude": (item.get("coordinate") or {}).get("latitude"),
            "Longitude": (item.get("coordinate") or {}).get("longitude"),
        }
        for item in items
    ]
    df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    # Rename columns to lowercase and snake_case
    return df.rename(columns=lambda col: col.strip().lower().replace(" ", "_"))


def scrape_lunchcheck(base_url, output_filename):
    """
    Fetches restaurant data from the Lunch-Check directory API and saves it to a CSV file.

    Args:
        base_url (str): The base URL of the Lunch-Check directory web app.
        output_filename (str): The filename for the output CSV file (written under ./data).
    """
    if not output_filename:
        raise ValueError("Output filename must be provided.")
    output_path = Path.cwd() / "data" / output_filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    items = fetch_restaurants(base_url)
    if not items:
        raise RuntimeError("No restaurants were returned.")

    df = to_dataframe(items)
    df.to_csv(output_path, encoding="utf-8", index=False)
    print(f"Successfully fetched {len(df)} restaurants and saved to {output_path}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetches restaurant data from the Lunch-Check directory and saves it to a CSV file."
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=DEFAULT_BASE_URL,
        help=f"URL of the Lunch-Check directory web app (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument("--output-filename", type=str, help="Filename for the output CSV file.")
    # Kept so existing callers (run_weekly_pipeline.py, the workflow) don't break; no browser is used anymore.
    parser.add_argument("--headless", action="store_true", help="Deprecated, ignored.")
    parser.add_argument("--max-pages", type=int, default=-1, help="Deprecated, ignored.")

    args = parser.parse_args()
    scrape_lunchcheck(base_url=args.base_url, output_filename=args.output_filename)

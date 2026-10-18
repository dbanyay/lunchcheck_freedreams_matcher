import argparse
import json
import re
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

DEFAULT_CACHE_PATH = Path(".cache") / "hotel_details.json"
DEFAULT_REFRESH_DAYS = 60  # re-read an address after this long, in case a hotel moved or changed its details
ADDRESS_SELECTOR = "p.s-address"
MAX_CONSECUTIVE_FAILURES = 5

# Cache entries written by an older version of this script (without the pseudo theme "SKI") are re-read.
SCHEMA_VERSION = 2

# Downhill skiing, as opposed to the "Wintersport" theme which also covers cross-country skiing, snowshoeing and
# sledging ("Langlaufski" and "Schlittenpisten" must NOT match, hence the word-start anchors).
DOWNHILL_SKI_RE = re.compile(
    r"\bski(?:gebiet|lift|piste|pisten|schule|pass|verleih|fahr\w*|bus|region|ort|arena|-)"
    r"|\bski\s+fahr\w*"
    r"|\bpistenkilometer|\bsessellift|\bgondelbahn|\bluftseilbahn|\bskilifte|\bschneesportschule|\bskipisten"
    r"|\bski-\s*und\b",
    re.IGNORECASE,
)


def detect_themes(js_themes, page_text):
    """The theme headings found on the page, plus the pseudo theme "SKI" if the page mentions downhill skiing."""
    themes = list(js_themes)
    if DOWNHILL_SKI_RE.search(page_text or ""):
        themes.append("SKI")
    return themes


# The "Themen" headings on a hotel page that become flags on the map. Matched case-insensitively against the
# own text of any element, so the exact page structure does not matter.
THEME_NAMES = ["WANDERN", "WINTERSPORT", "WELLNESS", "ÖV-FREUNDLICH"]

# Reads the schema.org PostalAddress microdata and the theme headings of a hotel detail page in one round-trip.
EXTRACT_DETAILS_JS = """
const themeNames = arguments[0];
const root = document.querySelector('p.s-address');
if (!root) return null;
const page = document.querySelector('.js-hotel-detail-page') || document.body;
const themes = new Set();
page.querySelectorAll('*').forEach(el => {
    const own = Array.from(el.childNodes).filter(n => n.nodeType === 3)
        .map(n => n.textContent).join('').replace(/\\s+/g, ' ').trim().toUpperCase();
    if (themeNames.includes(own)) themes.add(own);
});
const field = name => {
    const el = root.querySelector('[itemprop="' + name + '"]');
    return el ? el.textContent.replace(/\\s+/g, ' ').trim() : '';
};
return {
    street: field('streetAddress'),
    zip_code: field('postalCode'),
    city: field('addressLocality'),
    region: field('addressRegion'),
    themes: themeNames.filter(name => themes.has(name)),
};
"""


def setup_driver(headless):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--log-level=3")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    # Only text is needed
    options.add_experimental_option("prefs", {"profile.managed_default_content_settings.images": 2})
    service = webdriver.ChromeService(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def load_cache(cache_path):
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    # Entries from before dates were recorded count as fetched today
    for details in cache.values():
        details.setdefault("fetched_at", date.today().isoformat())
    return cache


def is_stale(details, refresh_days):
    if details.get("version") != SCHEMA_VERSION:   # cached by an older version of this script
        return True
    try:
        return date.fromisoformat(details["fetched_at"]) < date.today() - timedelta(days=refresh_days)
    except (KeyError, ValueError):
        return True


def save_cache(cache_path, cache):
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def collect_swiss_hotel_urls(input_files):
    """Unique hotel URLs of all Swiss hotels in the given Freedreams CSVs (same 'CH' filter as merge_datasets.py)."""
    urls = []
    for input_file in input_files:
        df = pd.read_csv(input_file)
        df = df[df["location"].astype(str).str.contains(r",\s*CH$", na=False, regex=True)]
        urls.extend(df["webpage"].dropna().tolist())
    return list(dict.fromkeys(urls))


def scrape_hotel_details(input_files, output_filename, cache_path, headless=True, delay=1.0, max_hotels=-1,
                         wait_time=15, refresh_days=DEFAULT_REFRESH_DAYS):
    """
    Reads street address and ZIP code from every Swiss hotel's Freedreams page and saves them to a CSV.

    Addresses rarely change, so results are cached by URL in `cache_path` and only new hotels, hotels that
    could not be read before, and entries older than `refresh_days` need a page load. Hotels that disappear from
    Freedreams drop out of the output automatically (it is built from the current hotel lists only), but stay in
    the cache, so a hotel that comes back does not need to be fetched again. A failed refresh keeps the old entry.
    """
    output_path = Path.cwd() / "data" / output_filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    urls = collect_swiss_hotel_urls(input_files)
    cache = load_cache(cache_path)
    missing = [url for url in urls if url not in cache or is_stale(cache[url], refresh_days)]
    if max_hotels > 0:
        missing = missing[:max_hotels]
    print(f"{len(urls)} Swiss hotels, {len(urls) - len(missing)} up to date in cache, {len(missing)} to fetch.")

    if missing:
        driver = setup_driver(headless)
        wait = WebDriverWait(driver, wait_time)
        consecutive_failures = 0
        try:
            for position, url in enumerate(missing, start=1):
                print(f"({position}/{len(missing)}) {url}")
                try:
                    driver.get(url)
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ADDRESS_SELECTOR)))
                    details = driver.execute_script(EXTRACT_DETAILS_JS, THEME_NAMES)
                    if details:
                        page_text = driver.execute_script(
                            "return (document.querySelector('.js-hotel-detail-page') || document.body).textContent;")
                        details["themes"] = detect_themes(details["themes"], page_text)
                except (TimeoutException, WebDriverException) as error:
                    consecutive_failures += 1
                    print(f"  failed ({type(error).__name__}); title: {driver.title!r}")
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        print("Too many consecutive failures - the site may be rate-limiting. Stopping early.")
                        break
                    continue

                if not details or not details.get("street"):
                    print("  no address found on page")
                    continue

                consecutive_failures = 0
                cache[url] = {**details, "fetched_at": date.today().isoformat(), "version": SCHEMA_VERSION}
                print(f"  {details['street']}, {details['zip_code']} {details['city']}")
                if position % 10 == 0:
                    save_cache(cache_path, cache)
                time.sleep(delay)
        finally:
            driver.quit()
            save_cache(cache_path, cache)

    rows = []
    for url in urls:
        if url in cache:
            details = {k: v for k, v in cache[url].items() if k not in ("fetched_at", "version")}
            details["themes"] = "|".join(details.get("themes", []))
            rows.append({"webpage": url, **details})
    if not rows:
        raise RuntimeError("No hotel addresses available.")
    pd.DataFrame(rows).to_csv(output_path, index=False)
    print(f"Saved addresses of {len(rows)}/{len(urls)} hotels to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reads street address and ZIP code of Swiss Freedreams hotels from their detail pages."
    )
    parser.add_argument("--input-files", type=str, nargs="+", required=True,
                        help="Freedreams CSV files (with 'location' and 'webpage' columns).")
    parser.add_argument("--output-filename", type=str, default="freedreams_hotel_details.csv",
                        help="Output CSV filename, written under ./data.")
    parser.add_argument("--cache-path", type=str, default=str(DEFAULT_CACHE_PATH),
                        help="JSON cache of already fetched hotel addresses.")
    parser.add_argument("--headless", action="store_true", help="Run Chrome headless.")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds to pause between page loads.")
    parser.add_argument("--max-hotels", type=int, default=-1, help="Fetch at most this many uncached hotels.")
    parser.add_argument("--refresh-days", type=int, default=DEFAULT_REFRESH_DAYS,
                        help="Re-read cached addresses older than this many days.")
    args = parser.parse_args()

    scrape_hotel_details(
        input_files=[Path.cwd() / f for f in args.input_files],
        output_filename=args.output_filename,
        cache_path=Path.cwd() / args.cache_path,
        headless=args.headless,
        delay=args.delay,
        max_hotels=args.max_hotels,
        refresh_days=args.refresh_days,
    )

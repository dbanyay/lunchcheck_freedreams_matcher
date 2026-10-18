# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Finds Swiss hotels on Freedreams (room-free stays, pay only for meals) that have a restaurant accepting Lunch-Check. It scrapes both sites with Selenium, fuzzy-matches names/locations, then generates HTML maps/reports published via GitHub Pages (`index.html` + `results/*.html`).

## Commands

Uses `uv` (Python >=3.12). No tests or linter are configured.

```bash
uv sync --frozen
uv run python src/run_weekly_pipeline.py            # full pipeline, driven by params.yaml
uv run python src/run_weekly_pipeline.py --no-clean --n-jobs 1
```

Each stage is also a standalone CLI (see `.github/workflows/weekly-pages-update.yml` for exact args):

```bash
uv run python src/scrape_lunchcheck.py --base-url https://directory.lunch-check.ch/ --output-filename lunchcheck_restaurants.csv
uv run python src/scrape_freedreams.py --base-url <url> --output-filename freedreams_restaurants_2nights.csv --num-nights 2
uv run python src/scrape_hotel_details.py --input-files data/freedreams_restaurants_2nights.csv data/freedreams_restaurants_3nights.csv --headless
uv run python src/merge_datasets.py --input-files data/lunchcheck_restaurants.csv data/freedreams_hotel_details.csv data/freedreams_restaurants_2nights.csv ... --output-path output
uv run python src/collect_info.py --input-file output/filtered_matches_2nights.csv --output-screenshots-html-path results/2_nights_info.html --output-map-html-path results/2_nights_map.html
uv run python src/generate_github_page.py --index-file index.html
```

## Architecture

Pipeline (`src/run_weekly_pipeline.py` orchestrates by spawning each script as a subprocess):

1. `scrape_lunchcheck.py` — no browser: reads the backend URL from the directory's `appsettings.json` and POSTs one unfiltered `/restaurants/search` (Blazor WASM site; returns all ~9.6k restaurants at once, incl. coordinates, no phone numbers) → `data/lunchcheck_restaurants.csv`
2. `scrape_freedreams.py` (one run per `--num-nights`, 2 and 3; run in parallel locally via Popen) → `data/freedreams_restaurants_{N}nights.csv`
3. `scrape_hotel_details.py` — Selenium; reads street/ZIP (schema.org `p.s-address` microdata) from each Swiss hotel's detail page, cached by URL in `.cache/hotel_details.json` so later runs only fetch new hotels → `data/freedreams_hotel_details.csv`
4. `merge_datasets.py` — matches hotels to restaurants **by address**, not by name: `address_matching.py` parses street + house number and compares ZIP, normalised street similarity and number. Tiers (`Address_Match` column): `exact`; `street_no_number` (also needs a name score >= `street_only_min_name_score`); `name_same_zip` (different street designation but near-identical name). Input files are told apart by file name (`lunch`, `details`, otherwise a freedreams list) → `output/filtered_matches_{N}nights.csv`
5. `collect_info.py` — per matched CSV (one marker per hotel even if several restaurants match), screenshots the top of each hotel page as cropped JPEG (full size for the info page, thumbnail for the map popup), pins the map at the restaurant's Lunch-Check coordinates (Nominatim geocoding with `.cache/geocode_cache.json` only as fallback), colours pins by `hotel_status.json` → `results/` map + info HTML
6. `generate_github_page.py` — updates the last-update date in `index.html`

Key points:
- `params.yaml` is the single source of truth for the local pipeline (URLs, match thresholds, headless flags, nights list, output paths, collect jobs). Adding a night variant means adding entries to both `freedreams_scrapes` and `collect_info_jobs`.
- The GitHub Actions workflow (`weekly-pages-update.yml`, Sundays 05:00 UTC) re-implements the pipeline as separate jobs passing CSVs via artifacts, with **hardcoded args duplicated from params.yaml** (including a different Freedreams URL, `/de/suche`). Keep both in sync when changing paths or filenames. Freedreams scraping runs non-headless under `xvfb-run`.
- The final job commits `index.html` and the four `results/*.html` files back to the repo. `.gitignore` ignores `data/`-style intermediates, `output/`, and everything in `results/` except those four files.
- `hotel_status.json` (checked in, edited by hand; **public** via GitHub Pages) records per hotel `status`: `stayed` (green), `positive` (yellow: replied positively, not stayed), `rejected` (red: hotel says Freedreams + Lunch-Check is not possible), `unknown` (grey, also the default for hotels without an entry); an optional `note` is shown in the popup. Statuses only colour hotels that are in the current matches; a hotel that is not currently offered is not drawn, and its entry just waits. Entries match a hotel by `urls` or by a `match` pattern (`name_contains` + `location_contains`), because Freedreams removes and re-adds hotels, sometimes under a new URL.
- Hotel-address cache entries in `.cache/hotel_details.json` carry a `fetched_at` date and are re-read after 60 days (`--refresh-days`). Hotels that vanish from Freedreams drop out of the output automatically (it is built from the current lists) but stay cached, so a returning hotel costs no page load.
- `.cache/` (gitignored) holds the hotel-address and geocoding caches; in CI they persist between weekly runs via `actions/cache`.
- `.dvc/` exists but is gitignored; DVC is not part of the workflow.

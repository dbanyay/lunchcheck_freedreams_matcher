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
uv run python src/merge_datasets.py --input-files data/lunchcheck_restaurants.csv data/freedreams_restaurants_2nights.csv ... --output-path output --n-jobs 1
uv run python src/collect_info.py --input-file output/filtered_matches_2nights.csv --output-screenshots-html-path results/2_nights_info.html --output-map-html-path results/2_nights_map.html
uv run python src/generate_github_page.py --index-file index.html
```

## Architecture

Pipeline (`src/run_weekly_pipeline.py` orchestrates by spawning each script as a subprocess):

1. `scrape_lunchcheck.py` — no browser: reads the backend URL from the directory's `appsettings.json` and POSTs one unfiltered `/restaurants/search` (Blazor WASM site; returns all ~9.6k restaurants at once, no phone numbers) → `data/lunchcheck_restaurants.csv`
2. `scrape_freedreams.py` (one run per `--num-nights`, 2 and 3; run in parallel locally via Popen) → `data/freedreams_restaurants_{N}nights.csv`
3. `merge_datasets.py` — identifies the lunchcheck vs freedreams CSVs among `--input-files`, fuzzy-matches (fuzzywuzzy, joblib-parallel) → `output/filtered_matches_{N}nights.csv`
4. `collect_info.py` — per matched CSV, geocodes (geopy), screenshots hotel pages, writes a map HTML and an info HTML into `results/`
5. `generate_github_page.py` — updates the last-update date in `index.html`

Key points:
- `params.yaml` is the single source of truth for the local pipeline (URLs, match thresholds, headless flags, nights list, output paths, collect jobs). Adding a night variant means adding entries to both `freedreams_scrapes` and `collect_info_jobs`.
- The GitHub Actions workflow (`weekly-pages-update.yml`, Sundays 05:00 UTC) re-implements the pipeline as separate jobs passing CSVs via artifacts, with **hardcoded args duplicated from params.yaml** (including a different Freedreams URL, `/de/suche`). Keep both in sync when changing paths or filenames. Freedreams scraping runs non-headless under `xvfb-run`.
- The final job commits `index.html` and the four `results/*.html` files back to the repo. `.gitignore` ignores `data/`-style intermediates, `output/`, and everything in `results/` except those four files.
- `.dvc/` exists but is gitignored; DVC is not part of the workflow.

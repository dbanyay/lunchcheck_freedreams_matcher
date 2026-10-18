import argparse
from collections import defaultdict
from pathlib import Path

import pandas as pd
import yaml
from fuzzywuzzy import fuzz

from address_matching import STREET_SIMILARITY_DEFAULT, compare_addresses, parse_street_address

# Order of confidence: an exact address match ranks above a street-only match, which ranks above a
# same-ZIP match that is only confirmed by a near-identical name.
ADDRESS_MATCH_RANK = {"exact": 0, "street_no_number": 1, "name_same_zip": 2}
NAME_MATCH_SCORE_DEFAULT = 90
NO_NUMBER_MIN_NAME_SCORE_DEFAULT = 60

OUTPUT_COLUMNS = [
    "freedreams_hotel_name", "lunchcheck_restaurant_name",
    "freedreams_location", "freedreams_street", "freedreams_zip_code",
    "lunchcheck_address", "lunchcheck_zip_code", "lunchcheck_city", "lunchcheck_canton", "lunchcheck_phone",
    "lunchcheck_latitude", "lunchcheck_longitude",
    "freedreams_rating", "freedreams_num_stars", "freedreams_webpage",
    "Address_Match", "Match_Score",
]


def parse_arguments():
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Matches Freedreams hotels with Lunch-Check restaurants by street address."
    )
    parser.add_argument(
        "--input-files",
        type=str,
        nargs='+',
        help="Input CSV files: the lunchcheck restaurants, the freedreams hotel details (street/ZIP) "
             "and one or more freedreams hotel lists."
    )
    parser.add_argument(
        "--output-path",
        type=str,
        help="Output directory for the result."
    )
    parser.add_argument(
        "--n-jobs",
        type=int,
        default=1,
        help="Ignored; kept so existing callers keep working."
    )
    return parser.parse_args()


def find_and_load_data(input_files):
    """
    Sorts the input CSVs into the lunchcheck restaurants, the freedreams hotel details and the freedreams hotel lists
    (recognised by their file names).

    Returns:
        tuple: (df_lunchcheck, df_details, freedreams_dfs) where freedreams_dfs maps file name to DataFrame.
    """
    freedreams_dfs = {}
    df_lunchcheck = pd.DataFrame()
    df_details = pd.DataFrame()

    for csv_path in input_files:
        print(f"Processing {csv_path.name}")
        try:
            name = csv_path.name.lower()
            if "lunch" in name:
                df_lunchcheck = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
            elif "details" in name:
                df_details = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
            else:
                df = pd.read_csv(csv_path)
                if "Unnamed: 0" in df.columns:
                    df.drop(columns=["Unnamed: 0"], inplace=True)
                df = df[df["location"].astype(str).str.contains(r',\s*CH$', na=False, regex=True)]
                freedreams_dfs[csv_path.name] = df
        except Exception as e:
            print(f"Error reading {csv_path.name}: {e}. Skipping this file.")

    if df_lunchcheck.empty:
        raise ValueError("No 'lunch' CSV file found. Cannot perform matching.")
    if df_details.empty:
        raise ValueError("No hotel 'details' CSV file found. Run scrape_hotel_details.py first.")
    return df_lunchcheck, df_details, freedreams_dfs


def index_restaurants_by_zip(df_lunchcheck):
    """Parses every restaurant address once and groups the restaurants by ZIP code."""
    by_zip = defaultdict(list)
    for position, (address, zip_code) in enumerate(zip(df_lunchcheck["address"], df_lunchcheck["zip_code"])):
        parsed = parse_street_address(address, zip_code)
        if parsed.zip_code:
            by_zip[parsed.zip_code].append((position, parsed))
    return by_zip


def find_address_matches(df_freedreams, df_details, df_lunchcheck, restaurants_by_zip, min_street_similarity,
                         min_name_score, min_name_score_without_number):
    """
    Matches each hotel to the restaurants at the same address (see compare_addresses), and additionally to
    restaurants in the same ZIP code whose name is almost identical: the two sites sometimes describe the same
    place with a different street designation (e.g. "Pass dal Fuorn" vs "Süsom Givé 82").

    Returns:
        list: One dictionary per (hotel, restaurant) match.
    """
    details_by_url = df_details.drop_duplicates("webpage").set_index("webpage").to_dict("index")
    matches = []
    hotels_without_details = 0

    for _, row_fd in df_freedreams.iterrows():
        details = details_by_url.get(row_fd["webpage"])
        if not details or not details.get("street"):
            hotels_without_details += 1
            continue
        hotel_address = parse_street_address(details["street"], details.get("zip_code", ""))

        for position, restaurant_address in restaurants_by_zip.get(hotel_address.zip_code, []):
            row_lc = df_lunchcheck.iloc[position]
            # How similar the names are: also helps to spot a different business at the same address
            name_score = fuzz.token_set_ratio(row_fd["hotel_name"], row_lc["restaurant_name"])

            address_match = compare_addresses(hotel_address, restaurant_address, min_street_similarity)
            if address_match == "street_no_number" and name_score < min_name_score_without_number:
                address_match = None   # a bare street name (e.g. a village square) is too vague on its own
            if not address_match and name_score >= min_name_score:
                address_match = "name_same_zip"
            if not address_match:
                continue
            matches.append({
                **row_fd.add_prefix('freedreams_').to_dict(),
                "freedreams_street": details["street"],
                "freedreams_zip_code": details.get("zip_code", ""),
                **row_lc.add_prefix('lunchcheck_').to_dict(),
                "Address_Match": address_match,
                "Match_Score": name_score,
            })

    if hotels_without_details:
        print(f"Warning: {hotels_without_details} hotels have no address details and could not be matched.")
    return matches


def main():
    """Main function to run the address matching process."""
    args = parse_arguments()

    if len(args.input_files) < 3:
        print("Error: Please provide a lunchcheck file, a hotel details file and at least one freedreams file.")
        return
    input_files = [Path.cwd() / input_file for input_file in args.input_files]

    output_dir = Path.cwd() / args.output_path
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory set to: {output_dir}")

    params_file = Path.cwd() / "params.yaml"
    if not params_file.exists():
        print(f"Error: params.yaml file not found in {params_file}. Please ensure it exists.")
        return
    with open(params_file, 'r', encoding='utf-8') as file:
        params = yaml.safe_load(file)
    merge_params = params["merge_datasets"]
    min_street_similarity = merge_params.get("street_match_score", STREET_SIMILARITY_DEFAULT)
    min_name_score = merge_params.get("name_match_score", NAME_MATCH_SCORE_DEFAULT)
    min_name_score_without_number = merge_params.get(
        "street_only_min_name_score", NO_NUMBER_MIN_NAME_SCORE_DEFAULT
    )

    df_lunchcheck, df_details, freedreams_dfs = find_and_load_data(input_files)
    restaurants_by_zip = index_restaurants_by_zip(df_lunchcheck)

    for freedreams_filename, freedreams_df in freedreams_dfs.items():
        print(f"\nMatching {freedreams_filename} with lunchcheck data by address...")
        matches = find_address_matches(
            freedreams_df, df_details, df_lunchcheck, restaurants_by_zip, min_street_similarity,
            min_name_score, min_name_score_without_number
        )

        if not matches:
            print(f"No address matches found for {freedreams_filename}.")
            continue

        results_df = pd.DataFrame(matches)
        results_df = results_df[[column for column in OUTPUT_COLUMNS if column in results_df.columns]]
        results_df = results_df.assign(_rank=results_df["Address_Match"].map(ADDRESS_MATCH_RANK)).sort_values(
            by=["_rank", "Match_Score"], ascending=[True, False], kind="stable"
        ).drop(columns="_rank").reset_index(drop=True)

        output_filename = output_dir / f"filtered_matches_{freedreams_filename.split('_')[-1]}"
        results_df.to_csv(output_filename, index=False)
        by_type = results_df["Address_Match"].value_counts().to_dict()
        print(f"Found {len(results_df)} matches {by_type} for {freedreams_filename}, saved to {output_filename}")


if __name__ == "__main__":
    main()

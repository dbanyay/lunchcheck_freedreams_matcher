import argparse
from pathlib import Path
import pandas as pd
from fuzzywuzzy import fuzz
from tqdm import tqdm
from joblib import Parallel, delayed
import os
import yaml


def parse_arguments():
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Parallel fuzzy matching of hotel/restaurant names from CSV files."
    )
    parser.add_argument(
        "--input-files",
        type=str,
        nargs='+',
        help="List of input CSV file names. Provide both lunchcheck and freedreams files."
    )
    parser.add_argument(
        "--output-path",
        type=str,
        help="Output file path for the result."
    )

    parser.add_argument(
        "--n-jobs",
        type=int,
        default=1,
        help="Number of parallel jobs to run. Set to 1 for sequential execution. Default is 1."
    )
    return parser.parse_args()

def find_and_load_data(input_dir):
    """
    Finds and loads the lunchcheck DataFrame and other freedreams DataFrames from the input directory.

    Args:
        input_dir (Path): The path to the directory containing CSV files.
        lunchcheck_col (str): The column name for restaurant names in the lunchcheck file.
        freedreams_location_col_original (str): The original column name for location in freedreams files.

    Returns:
        tuple: A tuple containing df_lunchcheck (pd.DataFrame) and freedreams_dfs (dict).
    """
    freedreams_dfs = {}
    df_lunchcheck = pd.DataFrame()

    print(f"Scanning for CSV files in: {input_dir}")

    for csv_path in input_dir:
        print(f"Processing {csv_path.name}")
        try:
            df = pd.read_csv(csv_path)
            if "Unnamed: 0" in df.columns:
                df.drop(columns=["Unnamed: 0"], inplace=True)
            if "lunch" in str(csv_path.name).lower():
                df_lunchcheck = df
            else:
                df = df[df["location"].astype(str).str.contains('CH', na=False)]
                freedreams_dfs[csv_path.name] = df
        except Exception as e:
            print(f"Error reading {csv_path.name}: {e}. Skipping this file.")
            continue

    if df_lunchcheck.empty:
        raise ValueError("No 'lunch' CSV file found with the specified column. Cannot perform matching.")

    return df_lunchcheck, freedreams_dfs

def process_freedreams_row(row_fd, df_lunchcheck, restaurant_match_score):
    """
    Compares a single freedreams row against all lunchcheck rows and returns matches.

    Args:
        row_fd (pd.Series): A single row from the freedreams DataFrame.
        df_lunchcheck (pd.DataFrame): The entire lunchcheck DataFrame.
        restaurant_match_score (int): Minimum score for a match.

    Returns:
        list: A list of dictionaries, where each dictionary represents a match.
    """
    row_matches = []
    freedreams_name = row_fd.get("hotel_name", "")

    # Skip if freedreams_name is empty or not found
    if not freedreams_name:
        return row_matches

    for _, row_lc in df_lunchcheck.iterrows():
        lunchcheck_name = row_lc.get("restaurant_name", "")

        # Skip if lunchcheck_name is empty or not found
        if not lunchcheck_name:
            continue

        score = fuzz.token_set_ratio(freedreams_name, lunchcheck_name)

        if score >= restaurant_match_score:
            # Add prefixes to column names to distinguish source
            row_fd_renamed = row_fd.add_prefix('freedreams_')
            row_lc_renamed = row_lc.add_prefix('lunchcheck_')

            # Combine the rows and add the score
            combined_row = pd.concat([row_fd_renamed, row_lc_renamed])
            combined_row['Match_Score'] = score
            row_matches.append(combined_row.to_dict())
    return row_matches

def main():
    """Main function to run the fuzzy matching process."""
    args = parse_arguments()

    if len(args.input_files) < 2:
        print("Error: Please provide at least one lunchcheck file and one freedreams file.")
        return
    input_files = [Path.cwd() / input_file for input_file in args.input_files]

    output_dir = Path.cwd() / args.output_path

    n_jobs = args.n_jobs

    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory set to: {output_dir}")

    # load params yaml
    params_file = Path.cwd() / "params.yaml"
    if not params_file.exists():
        print(f"Error: params.yaml file not found in {params_file}. Please ensure it exists.")
        return
    with open(params_file, 'r', encoding='utf-8') as file:
        params = yaml.safe_load(file)

    restaurant_match_score = params["merge_datasets"].get('restaurant_match_score', 80)
    location_match_score = params["merge_datasets"].get('location_match_score', 80)

    # Load data
    df_lunchcheck, freedreams_dfs = find_and_load_data(input_files)

    for freedreams_filename, freedreams_df in freedreams_dfs.items():
        print(f"\nMatching {freedreams_filename} with lunchcheck data...")

        all_matches_for_file = []

        # Create a progress bar that updates as chunks are completed
        with tqdm(total=freedreams_df.shape[0], desc=f"Processing {freedreams_filename}") as pbar:
            # Parallel processing in chunks to update tqdm more frequently
            chunk_size = max(1, len(freedreams_df) // (n_jobs if n_jobs != -1 else os.cpu_count() or 10)) # Adjust chunk size
            for i in range(0, len(freedreams_df), chunk_size):
                chunk = freedreams_df.iloc[i:i+chunk_size]
                if n_jobs == 1:
                    chunk_results = [
                        process_freedreams_row(row_fd, df_lunchcheck, restaurant_match_score)
                        for _, row_fd in chunk.iterrows()
                    ]
                else:
                    chunk_results = Parallel(n_jobs=n_jobs)(
                        delayed(process_freedreams_row)(row_fd, df_lunchcheck, restaurant_match_score)
                        for _, row_fd in chunk.iterrows()
                    )
                for matches_from_row in chunk_results:
                    all_matches_for_file.extend(matches_from_row)
                pbar.update(len(chunk))

        if all_matches_for_file:
            results_df = pd.DataFrame(all_matches_for_file)
            results_df = results_df.sort_values(by='Match_Score', ascending=False).reset_index(drop=True)

            print(f"Found {len(results_df)} name matches in {freedreams_filename} with a score of {restaurant_match_score} or higher.")

            # Define the desired column order for the main results file
            desired_order_main = [
                "freedreams_hotel_name", "lunchcheck_restaurant_name",
                "freedreams_location", "lunchcheck_city", "lunchcheck_Address", "lunchcheck_zip_code",
                "lunchcheck_canton", "lunchcheck_phone",
                "freedreams_rating", "freedreams_num_stars",
                "freedreams_webpage", "Match_Score"
            ]

            # Reorder columns and save the initial (name-matched) results
            # Ensure only existing columns are used for reordering to prevent KeyError
            cols_to_keep_main = [col for col in desired_order_main if col in results_df.columns]
            results_df = results_df[cols_to_keep_main]

            # Apply Levenshtein distance filtering for location/city
            print(f"Applying location filter with minimum score {location_match_score}...")

            # Calculate location scores
            results_df['Location_Match_Score'] = results_df.apply(
                lambda row: fuzz.token_set_ratio(
                    row["lunchcheck_city"],
                    row["freedreams_location"]
                ), axis=1
            )

            results_df_filtered = results_df[results_df['Location_Match_Score'] >= location_match_score]

            if not results_df_filtered.empty:
                # Define desired order for filtered results, including Location_Match_Score
                desired_order_filtered = desired_order_main + ['Location_Match_Score']
                cols_to_keep_filtered = [col for col in desired_order_filtered if col in results_df_filtered.columns]

                results_df_filtered = results_df_filtered[cols_to_keep_filtered].sort_values(
                    by=['Match_Score', 'Location_Match_Score'], ascending=[False, False]
                ).reset_index(drop=True)

                filtered_filename = output_dir / f"filtered_matches_{freedreams_filename.split('_')[-1]}"
                results_df_filtered.to_csv(filtered_filename, index=False)
                print(f"Filtered matches based on city/location for {freedreams_filename} saved to {filtered_filename}")
            else:
                print(f"No matches found for {freedreams_filename} after applying location filter with score {location_match_score}.")
        else:
            print(f"No name matches found for {freedreams_filename} with a score of {restaurant_match_score} or higher.")


if __name__ == "__main__":
    main()

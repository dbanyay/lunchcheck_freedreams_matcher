import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


def run_step(command: list[str], label: str) -> None:
    print(f"\n=== {label} ===")
    print(" ".join(command))
    subprocess.run(command, check=True)


def run_parallel_steps(steps: list[tuple[list[str], str]]) -> None:
    print("\n=== Parallel Freedreams scraping ===")
    processes: list[tuple[subprocess.Popen[str], str]] = []

    for command, label in steps:
        print(f"Starting: {label}")
        print(" ".join(command))
        process = subprocess.Popen(command, text=True)
        processes.append((process, label))

    failed_labels: list[str] = []
    for process, label in processes:
        return_code = process.wait()
        if return_code == 0:
            print(f"Finished: {label}")
        else:
            print(f"Failed: {label} (exit code {return_code})")
            failed_labels.append(label)

    if failed_labels:
        raise RuntimeError(
            "Parallel scrape step failed for: " + ", ".join(failed_labels)
        )


def clean_artifacts(project_root: Path, relative_paths: list[str]) -> None:
    print("\n=== Clean previous artifacts ===")
    cleaned_count = 0
    for rel_path in sorted(set(relative_paths)):
        target = project_root / rel_path
        if target.exists() and target.is_file():
            target.unlink()
            cleaned_count += 1
            print(f"Deleted: {rel_path}")
    if cleaned_count == 0:
        print("Nothing to clean.")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Runs the full weekly data pipeline and updates index.html."
    )
    parser.add_argument(
        "--project-root",
        type=str,
        default=str(Path.cwd()),
        help="Project root directory. Defaults to current working directory.",
    )
    parser.add_argument(
        "--n-jobs",
        type=int,
        default=None,
        help="Parallel jobs passed to merge_datasets.py. Overrides params.yaml when provided.",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Skip deleting previous generated artifacts before running.",
    )
    return parser.parse_args()


def load_params(params_path: Path) -> dict:
    with params_path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def get_weekly_config(params: dict[str, Any]) -> dict[str, Any]:
    weekly = params.get("weekly_pipeline")
    if not weekly:
        raise ValueError("Missing 'weekly_pipeline' section in params.yaml.")
    return weekly


def main() -> None:
    args = parse_arguments()
    project_root = Path(args.project_root).resolve()
    params = load_params(project_root / "params.yaml")
    weekly = get_weekly_config(params)
    python_bin = sys.executable

    lunchcheck_url = params["scrape_lunchcheck"]["base_url"]
    freedreams_url = params["scrape_freedreams"]["base_url"]

    lunchcheck_output = weekly["lunchcheck_output_filename"]
    freedreams_scrapes = weekly["freedreams_scrapes"]
    merge_output_path = weekly["merge_output_path"]
    collect_info_jobs = weekly["collect_info_jobs"]
    index_file = weekly["index_file"]
    n_jobs = args.n_jobs if args.n_jobs is not None else weekly.get("n_jobs", -1)
    clean_before_run = weekly.get("clean_before_run", True) and not args.no_clean
    lunchcheck_headless = weekly.get("lunchcheck_headless", True)
    freedreams_headless = weekly.get("freedreams_headless", False)

    merge_input_files = [f"data/{lunchcheck_output}"] + [
        f"data/{job['output_filename']}" for job in freedreams_scrapes
    ]
    clean_targets = merge_input_files.copy()
    for collect_job in collect_info_jobs:
        clean_targets.append(collect_job["input_file"])
        clean_targets.append(collect_job["output_screenshots_html_path"])
        clean_targets.append(collect_job["output_map_html_path"])

    lunchcheck_command = (
        [
            python_bin,
            "src/scrape_lunchcheck.py",
            "--base-url",
            lunchcheck_url,
            "--output-filename",
            lunchcheck_output,
        ],
        "Scrape Lunch-Check restaurants",
    )
    if lunchcheck_headless:
        lunchcheck_command[0].append("--headless")

    freedreams_commands: list[tuple[list[str], str]] = []
    for scrape_job in freedreams_scrapes:
        freedreams_commands.append(
            (
                [
                    python_bin,
                    "src/scrape_freedreams.py",
                    "--base-url",
                    freedreams_url,
                    "--output-filename",
                    scrape_job["output_filename"],
                    "--num-nights",
                    str(scrape_job["num_nights"]),
                ],
                f"Scrape Freedreams {scrape_job['num_nights']}-night hotels",
            )
        )
        if freedreams_headless:
            freedreams_commands[-1][0].append("--headless")

    commands = [
        (
            [
                python_bin,
                "src/merge_datasets.py",
                "--input-files",
                *merge_input_files,
                "--output-path",
                merge_output_path,
                "--n-jobs",
                str(n_jobs),
            ],
            "Merge and filter matched datasets",
        )
    ]

    for collect_job in collect_info_jobs:
        commands.append(
            (
                [
                    python_bin,
                    "src/collect_info.py",
                    "--input-file",
                    collect_job["input_file"],
                    "--output-screenshots-html-path",
                    collect_job["output_screenshots_html_path"],
                    "--output-map-html-path",
                    collect_job["output_map_html_path"],
                ],
                collect_job["label"],
            )
        )

    commands.append(
        (
            [python_bin, "src/generate_github_page.py", "--index-file", index_file],
            "Update index last update date",
        )
    )

    if clean_before_run:
        clean_artifacts(project_root=project_root, relative_paths=clean_targets)

    run_step(command=lunchcheck_command[0], label=lunchcheck_command[1])
    run_parallel_steps(steps=freedreams_commands)

    for command, label in commands:
        run_step(command=command, label=label)

    print("\nWeekly pipeline completed successfully.")


if __name__ == "__main__":
    main()

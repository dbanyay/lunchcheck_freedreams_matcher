import argparse
import re
from datetime import datetime
from pathlib import Path


LAST_UPDATE_PATTERN = re.compile(
    r"(Last update:\s*)([^<\n]+)",
    flags=re.IGNORECASE,
)


def format_last_update(now: datetime | None = None) -> str:
    date_value = now or datetime.now()
    return date_value.strftime("%B %-d, %Y")


def update_index_last_update(index_path: Path) -> bool:
    if not index_path.exists():
        raise FileNotFoundError(f"Index file not found: {index_path}")

    html_content = index_path.read_text(encoding="utf-8")
    replacement_value = f"\\1{format_last_update()}"
    updated_html, replacements = LAST_UPDATE_PATTERN.subn(replacement_value, html_content, count=1)

    if replacements == 0:
        raise ValueError("Could not find 'Last update:' marker in index file.")

    if updated_html == html_content:
        return False

    index_path.write_text(updated_html, encoding="utf-8")
    return True


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Updates the root GitHub Pages index with the latest generation date."
    )
    parser.add_argument(
        "--index-file",
        type=str,
        default="index.html",
        help="Path to the HTML index file to update. Defaults to index.html.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    index_path = Path.cwd() / args.index_file
    changed = update_index_last_update(index_path=index_path)

    if changed:
        print(f"Updated last update date in {index_path}.")
    else:
        print(f"No change required for {index_path}.")


if __name__ == "__main__":
    main()

import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
import time
from webdriver_manager.chrome import ChromeDriverManager  # Ensure this is installed if not already
from pathlib import Path
import argparse  # Import the argparse module


# Extracts all hotel cards of the current page in a single browser round-trip.
# (Per-element find_element calls cost one WebDriver round-trip each, ~6 per hotel.)
EXTRACT_HOTELS_JS = """
const clean = s => s.replace(/\\s+/g, ' ').trim();
return Array.from(document.querySelectorAll('article.s-hotel-item')).map(card => {
    const link = card.querySelector('h2 a');
    if (!link) return null;
    const location = card.querySelector('p');
    const rating = card.querySelector('.s-rating-summary');
    const stars = card.querySelector('.s-hotelstars');
    return {
        hotel_name: clean(card.querySelector('h2').textContent),
        location: location ? clean(location.textContent) : '',
        rating: rating ? clean(rating.textContent) : 'No rating',
        num_stars: stars ? stars.querySelectorAll('i').length : 0,
        webpage: link.href,
    };
}).filter(Boolean);
"""


def scrape_freedreams_hotels(base_url: str = "https://www.freedreams.ch/de/suche",
                             num_nights: int = 3,
                             max_pages: int = -1,
                             headless: bool = True,
                             output_filename: str = None,
                             wait_time: int = 10):
    """
    Scrapes hotel data from freedreams.ch based on specified criteria and saves it to a CSV file.

    Args:
        base_url (str): The base URL for the hotel search on freedreams.ch.
        num_nights (int): The number of nights for the hotel stay (e.g., 3).
        max_pages (int): The maximum number of pages to scrape. Use -1 to scrape all pages.
        headless (bool): If True, runs the Chrome browser in headless mode.
        output_file (str): The path and filename for the output CSV file. If not provided, a default name will be used.
        wait_time (int): The maximum time in seconds to wait for page elements to load.
    """

    if output_filename is None:
        raise ValueError("Output filename must be specified.")
    output_path = Path.cwd() / "data" / output_filename
    if not output_path.parent.exists():
        output_path.parent.mkdir(parents=True, exist_ok=True)

    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless")  # Enable this for production/speed
        print("Running browser in headless mode.")
    else:
        print("Running browser in headful (visible) mode.")

    # Only text is needed; skipping images makes every page load noticeably faster.
    chrome_options.add_experimental_option("prefs", {"profile.managed_default_content_settings.images": 2})

    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )

    # Use ChromeDriverManager to automatically handle driver installation
    service = webdriver.ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    wait = WebDriverWait(driver, wait_time)

    all_hotels = []

    try:
        print(f"Loading base URL: {base_url}")
        driver.get(base_url)

        # Step 1: Click duration dropdown
        print("Clicking duration dropdown...")
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "div.js-display-duration"))).click()

        # Step 2: Wait for dropdown to be visible
        print("Waiting for duration dropdown to be visible...")
        duration_menu = wait.until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "ul.js-duration-desktop"))
        )

        # Step 3: Select the correct number of nights
        li_selector = f'li.js-option[data-value="{num_nights}"]'
        print(f"Selecting {num_nights} nights...")
        duration_option = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, li_selector))
        )
        duration_option.click()

        # Step 4: Click "Suchen" button and wait until the results page has actually been replaced
        print("Clicking 'Suchen' button...")
        try:
            old_hotel_list = driver.find_element(By.CSS_SELECTOR, "section.s-hotel-list")
        except NoSuchElementException:
            old_hotel_list = None
        wait.until(EC.element_to_be_clickable((By.ID, "search_filter_search"))).click()
        if old_hotel_list is not None:
            wait.until(EC.staleness_of(old_hotel_list))
        else:
            time.sleep(3)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "article.s-hotel-item")))

        # Determine max_pages if not specified by argument
        if max_pages == -1:
            try:
                # Find the pagination element that contains the total number of pages
                # This XPath looks for a list item that is the last child in the pagination ul
                # and contains the text "Total" which seems to be the pattern on freedreams.
                # Adjust if the structure changes.
                total_pages_element = wait.until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//ul[contains(@class, 's-list-pagination')]//li[last()]/a"))
                )
                max_pages_text = total_pages_element.text.strip()
                if max_pages_text.isdigit():
                    max_pages = int(max_pages_text)
                    print(f"Detected {max_pages} total pages.")
                else:
                    # Fallback if the text is not just a number (e.g., "Page 1 of 10")
                    # Try to find the last page number from direct page links if available
                    page_links = driver.find_elements(By.CSS_SELECTOR, "ul.s-list-pagination a[href*='page=']")
                    if page_links:
                        max_pages = max(int(link.text) for link in page_links if link.text.isdigit())
                        print(f"Detected {max_pages} pages from pagination links.")
                    else:
                        print("Could not reliably determine max pages. Proceeding with default (or limited scrape).")
                        max_pages = 1  # Default to 1 page if unable to determine

            except TimeoutException:
                print("Pagination element not found. Assuming single page or limited results.")
                max_pages = 1  # If no pagination, assume only one page
            except Exception as e:
                print(f"Error determining max pages: {e}. Defaulting to 1 page if not explicitly set.")
                max_pages = 1  # Fallback in case of other errors

        print(f"Scraping up to {max_pages} pages.")

        # Scrape and paginate
        for page in range(1, max_pages + 1):
            print(f"\n--- Scraping Page {page}/{max_pages} ---")
            if page > 1:
                try:
                    # Locate the pagination link for the desired page
                    # Ensure we are waiting for the page link to be clickable after previous page load
                    pagination_link_selector = f'ul.s-list-pagination > li > a[href="/de/suche?page={page}"]'
                    pagination_link = wait.until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, pagination_link_selector))
                    )

                    # Simulate a click on the pagination link
                    print(f"Clicking on page {page} link...")
                    # Store a reference to an element that is expected to become stale
                    old_hotel_list = wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "section.s-hotel-list")))
                    driver.execute_script("arguments[0].click();", pagination_link)

                    # Wait for the old element to become stale (page refresh)
                    wait.until(EC.staleness_of(old_hotel_list))
                    # Wait for the new page's main content to load
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "section.s-hotel-list")))
                except TimeoutException:
                    print(f"Timeout waiting for pagination link for page {page}. Ending pagination.")
                    break
                except StaleElementReferenceException:
                    print(f"Stale element encountered when trying to click page {page}. Retrying or breaking.")
                    # In a real scenario, you might want more robust retry logic
                    break  # Break if we consistently hit stale element on pagination
                except Exception as e:
                    print(f"Error navigating to page {page}: {e}. Ending pagination.")
                    break

            # Wait for hotel items to be present on the current page
            print(f"Extracting hotels from page {page}...")
            try:
                hotels = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "article.s-hotel-item")))
            except TimeoutException:
                print(
                    f"No hotel items found on page {page} after {wait_time} seconds. This page might be empty or an error occurred.")
                break  # Exit if no hotels found on a page

            if not hotels:
                print(f"No hotels found on page {page}. Ending scrape.")
                break

            all_hotels.extend(driver.execute_script(EXTRACT_HOTELS_JS))

            # Short pause between pages to be polite; the site rate-limits aggressive clients
            time.sleep(0.5)

    except Exception as e:
        print(f"An error occurred during the scraping process: {e}")
    finally:
        driver.quit()
        print("Browser session ended.")

    if all_hotels:
        df = pd.DataFrame(all_hotels)
        print(f"Scraped {len(df)} hotels.")

        # Save to csv
        df.to_csv(output_path, index=False)
        print(f"Data saved to {output_path}")
    else:
        print("No hotels were scraped.")


# --- Main execution block with argparse ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrapes hotel data from freedreams.ch based on specified criteria."
    )

    parser.add_argument(
        "--base-url",
        type=str,
        default="https://www.freedreams.ch/de/suche",
        help="Base URL for the hotel search on freedreams.ch (default: https://www.freedreams.ch/de/suche).",
    )

    parser.add_argument(
        "--output-filename",
        type=str,
        help="Output filename for the scraped hotel data",
    )
    parser.add_argument(
        "--num-nights",
        type=int,
        default=3,
        help="Number of nights for the hotel stay (default: 3).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=-1,
        help="Maximum number of pages to scrape. Use -1 to scrape all available pages (default: -1).",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run the Chrome browser in a visible (headful) mode instead of headless."
    )

    args = parser.parse_args()

    scrape_freedreams_hotels(
        base_url=args.base_url,
        num_nights=args.num_nights,
        max_pages=args.max_pages,
        headless=args.headless,
        output_filename=args.output_filename,
    )

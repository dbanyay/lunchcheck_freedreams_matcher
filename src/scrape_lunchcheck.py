import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
import time
from webdriver_manager.chrome import ChromeDriverManager
from pathlib import Path
from selenium.webdriver.support.ui import Select
import argparse # Import the argparse module

# --- Setup WebDriver ---
def setup_driver(headless=True):
    """
    Sets up and returns a Chrome WebDriver.
    Args:
        headless (bool): If True, runs Chrome in headless mode.
    """
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument('--headless')  # Run in headless mode
        print("Running browser in headless mode.")
    else:
        print("Running browser in headful (visible) mode.")

    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument(
        'user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
    options.add_argument('--start-maximized')

    service = webdriver.ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver


# --- Data Extraction Function ---
def extract_page_data(driver, wait_time):
    """
    Extracts restaurant data from the current page.
    Args:
        driver: Selenium WebDriver instance.
        wait_time (int): Maximum time to wait for elements to be present.
    Returns:
        list: A list of dictionaries, each representing a restaurant.
    """
    restaurants_on_page = []
    try:
        main_table_id = "ctl00_SheetContentPlaceHolder_ctl00_ctl01_GridView1"
        rows_xpath = f"//table[@id='{main_table_id}']/tbody/tr"

        rows = WebDriverWait(driver, wait_time).until(
            EC.presence_of_all_elements_located((By.XPATH, rows_xpath))
        )

        for row in rows:
            try:
                if "pager" in row.get_attribute("class"):
                    continue

                cols = row.find_elements(By.TAG_NAME, "td")

                col_contents = []
                for col in cols:
                    try:
                        span_element = col.find_element(By.TAG_NAME, "span")
                        col_contents.append(span_element.text.strip())
                    except NoSuchElementException:
                        col_contents.append("")
                    except StaleElementReferenceException:
                        col_contents.append("")
                    except Exception as e:
                        col_contents.append("")

                if all(not item for item in col_contents):
                    continue

                # The logic for column indexing is based on observations from the site.
                # It's better to make this more robust if possible (e.g., identify columns by headers if available).
                # For now, keeping the existing multiple conditions.
                if len(col_contents) == 13:
                    if col_contents[2] and col_contents[3]:
                        restaurants_on_page.append({
                            'Restaurant Name': col_contents[2],
                            'Address': col_contents[3],
                            'ZIP Code': col_contents[4],
                            'City': col_contents[5],
                            'Canton': col_contents[6],
                            'Phone': col_contents[7],
                        })
                elif len(col_contents) == 15:
                    if col_contents[4] and col_contents[5]:
                        restaurants_on_page.append({
                            'Restaurant Name': col_contents[4],
                            'Address': col_contents[5],
                            'ZIP Code': col_contents[6],
                            'City': col_contents[7],
                            'Canton': col_contents[8],
                            'Phone': col_contents[9],
                        })
                elif len(col_contents) == 17:
                    if col_contents[6] and col_contents[7]:
                        restaurants_on_page.append({
                            'Restaurant Name': col_contents[6],
                            'Address': col_contents[7],
                            'ZIP Code': col_contents[8],
                            'City': col_contents[9],
                            'Canton': col_contents[10],
                            'Phone': col_contents[11],
                        })
                elif len(col_contents) == 19:
                    if col_contents[8] and col_contents[9]:
                        restaurants_on_page.append({
                            'Restaurant Name': col_contents[8],
                            'Address': col_contents[9],
                            'ZIP Code': col_contents[10],
                            'City': col_contents[11],
                            'Canton': col_contents[12],
                            'Phone': col_contents[13],
                        })
                elif len(col_contents) == 21:
                    if col_contents[10] and col_contents[11]:
                        restaurants_on_page.append({
                            'Restaurant Name': col_contents[10],
                            'Address': col_contents[11],
                            'ZIP Code': col_contents[12],
                            'City': col_contents[13],
                            'Canton': col_contents[14],
                            'Phone': col_contents[15],
                        })
                else:
                    # Optional: Print row if it doesn't fit any known column structure for debugging
                    print(f"Skipping row with unexpected column count ({len(col_contents)}): {col_contents}")
                    pass

            except StaleElementReferenceException:
                print("StaleElementReferenceException encountered while processing a row. Skipping this row.")
                continue
            except NoSuchElementException as e:
                print(f"NoSuchElementException for a row's td elements: {e}. Skipping row.")
                continue
            except Exception as e:
                print(f"An unexpected error occurred while processing a row: {e}")
                continue

    except TimeoutException:
        print(f"Timeout waiting for main table rows to load on the page within {wait_time} seconds.")
    except Exception as e:
        print(f"An error occurred while extracting page data: {e}")

    return restaurants_on_page


# --- Main Scraper Function ---
def scrape_lunchcheck(base_url, output_filename, max_pages, headless):
    """
    Scrapes restaurant data from lunch-card.ch and saves it to a CSV file.

    Args:
        base_url (str): The base URL of the LunchCheck directory.
        output_filename (str): The filename for the output CSV file.
        max_pages (int): Maximum number of pages to scrape. Use -1 to scrape all available pages.
        headless (bool): If True, runs the browser in headless mode.
    """

    if not output_filename:
        raise ValueError("Output filename must be provided.")
    output_path = Path.cwd() / "data" / output_filename
    if not output_path.parent.exists():
        output_path.parent.mkdir(parents=True, exist_ok=True)

    driver = setup_driver(headless=headless)
    all_restaurants = []

    main_table_id = "ctl00_SheetContentPlaceHolder_ctl00_ctl01_GridView1"
    dropdown_page_size_id = "ctl00_SheetContentPlaceHolder_ctl00_ctl01_ddlPageSize"

    wait_time = 3

    try:
        driver.get(base_url)
        print(f"Navigating to {base_url}...")

        WebDriverWait(driver, wait_time).until(
            EC.presence_of_element_located((By.ID, main_table_id))
        )
        print("Initial table loaded.")

        print("Attempting to select 500 entries per page...")
        try:
            page_size_dropdown_element = WebDriverWait(driver, wait_time).until(
                EC.presence_of_element_located((By.ID, dropdown_page_size_id))
            )

            select = Select(page_size_dropdown_element)

            current_selection_value = select.first_selected_option.get_attribute("value")
            if current_selection_value != "500":
                print(f"Current page size is {current_selection_value}. Changing to 500.")
                select.select_by_value("500")

                print("Waiting for page to refresh after changing page size...")
                WebDriverWait(driver, wait_time).until(EC.staleness_of(page_size_dropdown_element))
                WebDriverWait(driver, wait_time).until(EC.presence_of_element_located((By.ID, main_table_id)))
                WebDriverWait(driver, wait_time).until(
                    EC.presence_of_all_elements_located((By.XPATH, f"//table[@id='{main_table_id}']/tbody/tr"))
                )
                print("Page refreshed with new page size (500).")
            else:
                print("Page already set to 500 entries per page. No action needed.")
        except TimeoutException:
            print(
                f"Timeout: Page size dropdown with ID '{dropdown_page_size_id}' not found within {wait_time} seconds. Continuing with default page size.")
        except Exception as e:
            print(f"An error occurred while trying to set page size: {e}. Continuing with current page size.")

        # Initialize current_page_number by reading from the UI
        try:
            active_page_span = WebDriverWait(driver, wait_time).until(
                EC.presence_of_element_located((By.XPATH, "//tr[@class='pager']//span"))
            )
            current_page_number = int(active_page_span.text.strip())
            print(f"Starting scraping from page {current_page_number}.")
        except (NoSuchElementException, TimeoutException, ValueError):
            print("Could not determine initial page number from UI. Starting from page 1.")
            current_page_number = 1

        while True:
            if max_pages > 0 and current_page_number > max_pages:
                print(f"Reached maximum page limit of {max_pages}. Ending scrape.")
                break
            print(f"Scraping page {current_page_number}...")

            # Pass wait_time to extract_page_data
            current_page_data = extract_page_data(driver, wait_time)
            all_restaurants.extend(current_page_data)
            print(f"Found {len(current_page_data)} restaurants on page {current_page_number}.")

            # --- Pagination Logic ---
            next_page_link_element = None
            pagination_advanced = False

            # First, check if the current page is the last page by looking for the next sequential number.
            # If the next sequential number is not found, we assume we are on the last visible page.
            try:
                # Try to find the link for the next sequential page number (current_page_number + 1)
                next_page_to_click = current_page_number + 1
                next_page_link_element = WebDriverWait(driver, wait_time).until(
                    EC.element_to_be_clickable((By.XPATH,
                                                f"//tr[@class='pager']//a[contains(@href, '__doPostBack') and text()='{next_page_to_click}']"
                                                ))
                )
                print(f"Found link for page {next_page_to_click}.")

            except TimeoutException:
                # If the next sequential page link is not found, it means we are either on the last page
                # or need to click '...' to reveal more page numbers.
                print(f"Link for page {next_page_to_click} not found directly.")
                try:
                    # Attempt to find and click the "..." link if available
                    ellipsis_link = WebDriverWait(driver, wait_time).until(
                        EC.element_to_be_clickable((By.XPATH,
                                                    "//tr[@class='pager']//a[contains(@href, '__doPostBack') and text()='...']"
                                                    ))
                    )
                    print("Found '...' (ellipsis) link. Clicking it to reveal more pages.")
                    # Click the ellipsis link
                    old_table = WebDriverWait(driver, wait_time).until(
                        EC.presence_of_element_located((By.ID, main_table_id))
                    )
                    driver.execute_script("arguments[0].click();", ellipsis_link)
                    WebDriverWait(driver, wait_time).until(EC.staleness_of(old_table))
                    WebDriverWait(driver, wait_time).until(
                        EC.presence_of_element_located((By.ID, main_table_id))
                    )
                    WebDriverWait(driver, wait_time).until(
                        EC.presence_of_all_elements_located(
                            (By.XPATH, f"//table[@id='{main_table_id}']/tbody/tr"))
                    )
                    # After clicking '...', the page numbers will change.
                    # We need to re-read the active page number from the UI.
                    active_page_span = WebDriverWait(driver, wait_time).until(
                        EC.presence_of_element_located((By.XPATH, "//tr[@class='pager']//span"))
                    )
                    new_active_page_number = int(active_page_span.text.strip())
                    if new_active_page_number > current_page_number:
                        current_page_number = new_active_page_number
                        pagination_advanced = True
                        print(f"Advanced to page {current_page_number} after clicking '...'.")
                    else:
                        print("Clicking '...' did not advance the page number. This might be the end or an issue.")
                        break  # Break if ellipsis doesn't advance
                    time.sleep(0.5)  # Give a moment for the page to fully render

                    # After clicking '...', now we look for the next sequential page *again*
                    # This is crucial because '...' reveals new numbers.
                    try:
                        next_page_to_click = current_page_number + 1
                        next_page_link_element = WebDriverWait(driver, wait_time).until(
                            EC.element_to_be_clickable((By.XPATH,
                                                        f"//tr[@class='pager']//a[contains(@href, '__doPostBack') and text()='{next_page_to_click}']"
                                                        ))
                        )
                        print(f"After '...', found link for page {next_page_to_click}.")
                    except TimeoutException:
                        print(
                            f"After '...', link for page {next_page_to_click} still not found. Assuming end of pagination.")
                        break  # If even after '...' we don't find the next page, it's the end.

                except TimeoutException:
                    print("No '...' (ellipsis) link found. Assuming end of pagination.")
                    break  # Neither sequential nor ellipsis link found, so it's the last page.

            # If a direct next page link was found (either initially or after '...')
            if next_page_link_element and not pagination_advanced:  # Only click if we haven't already advanced via '...'
                for attempt in range(3):
                    try:
                        # Re-locate the element just before clicking to ensure it's fresh
                        refreshed_next_page_link = WebDriverWait(driver, wait_time).until(
                            EC.element_to_be_clickable((By.XPATH,
                                                        f"//tr[@class='pager']//a[contains(@href, '__doPostBack') and text()='{next_page_to_click}']"
                                                        ))
                        )

                        print(f"Clicking link: {refreshed_next_page_link.text} (Attempt {attempt + 1})")

                        old_table = WebDriverWait(driver, wait_time).until(
                            EC.presence_of_element_located((By.ID, main_table_id))
                        )

                        driver.execute_script("arguments[0].click();", refreshed_next_page_link)

                        WebDriverWait(driver, wait_time).until(EC.staleness_of(old_table))

                        WebDriverWait(driver, wait_time).until(
                            EC.presence_of_element_located((By.ID, main_table_id))
                        )
                        WebDriverWait(driver, wait_time).until(
                            EC.presence_of_all_elements_located(
                                (By.XPATH, f"//table[@id='{main_table_id}']/tbody/tr"))
                        )
                        current_page_number += 1
                        pagination_advanced = True
                        time.sleep(0.1)  # Small delay for page stability
                        break
                    except StaleElementReferenceException:
                        print(f"StaleElementReferenceException encountered on attempt {attempt + 1}. Retrying...")
                        time.sleep(0.1)
                        if attempt == 2:
                            raise
                    except TimeoutException:
                        print(
                            f"Timeout while re-locating or clicking link on attempt {attempt + 1} within {wait_time} seconds. This indicates a serious issue. Breaking pagination.")
                        break
                    except Exception as e:
                        print(f"An unexpected error occurred during click attempt {attempt + 1}: {e}")
                        if attempt == 2:
                            raise
                        time.sleep(0.1)

            # If no pagination link was clicked, or pagination didn't advance, break the loop.
            if not pagination_advanced:
                print("No further pagination links found or pagination did not advance. Ending scrape.")
                break

            # Add a small delay to prevent rapid requests
            time.sleep(0.5)

    finally:
        driver.quit()
        print("Browser closed.")

    if all_restaurants:
        df = pd.DataFrame(all_restaurants)
        # Rename columns to lowercase and snake_case
        df = df.rename(columns=lambda col: col.strip().lower().replace(" ", "_"))
        df.to_csv(output_path, encoding='utf-8', index=False) # index=False to prevent writing pandas index
        print(f"\nSuccessfully scraped {len(df)} restaurants and saved to {output_path}.")
    else:
        print("No restaurants were scraped.")


# --- Main execution block with argparse ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrapes restaurant data from lunch-card.ch and saves it to a CSV file."
    )

    parser.add_argument(
        "--base-url",
        type=str,
        default="https://www.lunch-card.ch/public/LunchCheck/LC_Directory.aspx",
        help="Base URL for the LunchCheck directory (default: https://www.lunch-card.ch/public/LunchCheck/LC_Directory.aspx)"
    )

    parser.add_argument(
        "--output-filename",
        type=str,
        help="Filename for the output CSV file."
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
        help="Run the Chrome browser headless."
    )

    args = parser.parse_args()

    scrape_lunchcheck(
        base_url=args.base_url,
        output_filename=args.output_filename,
        max_pages=args.max_pages,
        headless=args.headless
    )

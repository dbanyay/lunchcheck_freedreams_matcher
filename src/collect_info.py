import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import base64
import argparse
from pathlib import Path
import json
import time # Import time for delays
from webdriver_manager.chrome import ChromeDriverManager

# Import Nominatim for geocoding
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

def setup_driver():
    """
    Sets up and returns a Selenium Chrome WebDriver instance.
    Configures the driver for headless mode and other common options.
    """
    chrome_options = webdriver.ChromeOptions()
    # Run in headless mode (no visible browser window)
    chrome_options.add_argument("--headless")
    # Bypass OS security model (necessary for some environments, e.g., Docker)
    chrome_options.add_argument("--no-sandbox")
    # Overcome limited resource problems
    chrome_options.add_argument("--disable-dev-shm-usage")
    # Suppress verbose logging from Chromium
    chrome_options.add_argument("--log-level=3")
    # Set a default window size, important for consistent screenshots in headless mode
    chrome_options.add_argument("--window-size=1920,1080")
    # Disable GPU hardware acceleration (often recommended for headless)
    chrome_options.add_argument("--disable-gpu")
    # Ignore certificate errors (useful for some development or self-signed certs)
    chrome_options.add_argument("--ignore-certificate-errors")
    # Disable browser extensions
    chrome_options.add_argument("--disable-extensions")
    # Disable setuid sandbox (another security bypass for certain environments)
    chrome_options.add_argument("--disable-setuid-sandbox")
    # Disable browser notifications
    chrome_options.add_argument("--disable-notifications")
    # Exclude specific switches to prevent certain console messages (e.g., DevTools listening)
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])

    # Setup WebDriver Service using webdriver-manager so local and CI environments behave similarly.
    try:
        service = Service(executable_path=ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except WebDriverException as e:
        print(f"Error initializing WebDriver: {e}")
        print("Could not initialize Chrome WebDriver with webdriver-manager.")
        return None


def scrape_hotel_images(df):
    """
    Reads URLs from the specified DataFrame, visits each URL, and scrapes a screenshot
    of the target div, returning a list of base64 encoded images with their URLs.
    """
    if 'freedreams_webpage' not in df.columns:
        print("Error: The DataFrame must contain a column named 'freedreams_webpage'.")
        return []

    image_data_list = []
    driver = setup_driver()
    if not driver:
        return []  # Exit if driver couldn't be initialized

    # Define the CSS selector for the target div
    target_div_selector = '.js-hotel-detail-page.s-hotel-detail-page.s-content-box.s-content-box-white-solid.is-relative'

    for index, row in df.iterrows():
        url = row['freedreams_webpage']
        if pd.isna(url) or not isinstance(url, str):
            print(f"Skipping row {index}: Invalid or missing URL.")
            image_data_list.append({
                'url': None, # Keep the structure, but indicate no image
                'image_base64': None,
                'index': index # Store original index for merging
            })
            continue

        print(f"Processing URL ({index + 1}/{len(df)}): {url}")
        try:
            driver.get(url)
            wait = WebDriverWait(driver, 20)
            target_div = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, target_div_selector)))
            png_bytes = target_div.screenshot_as_png
            base64_encoded_image = base64.b64encode(png_bytes).decode('utf-8')

            image_data_list.append({
                'url': url,
                'image_base64': base64_encoded_image,
                'index': index # Store original index for merging
            })
            print(f"Successfully scraped image for {url}")

        except TimeoutException:
            print(f"Timeout: The target element was not found on page for {url}. Skipping.")
            image_data_list.append({
                'url': url,
                'image_base64': None, # No image if timeout
                'index': index
            })
        except WebDriverException as e:
            print(f"WebDriver error occurred while processing {url}: {e}. Skipping.")
            image_data_list.append({
                'url': url,
                'image_base64': None,
                'index': index
            })
        except Exception as e:
            print(f"An unexpected error occurred for {url}: {e}. Skipping.")
            image_data_list.append({
                'url': url,
                'image_base64': None,
                'index': index
            })

    driver.quit()
    return image_data_list


def generate_html_report(image_data_list, output_html_path="hotel_screenshots.html"):
    """
    Generates an HTML file displaying all collected screenshots with their source URLs.
    """
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hotel Detail Page Screenshots</title>
    <style>
        /* Import Google Font - Inter for a modern look */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');

        body {
            font-family: 'Inter', sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f4f4f4; /* Light grey background */
            color: #333; /* Dark text for readability */
            line-height: 1.6;
        }

        .container {
            max-width: 900px; /* Max width for content */
            margin: 0 auto; /* Center the container */
            padding: 30px;
            background-color: #fff; /* White background for the content area */
            border-radius: 12px; /* Rounded corners for the container */
            box-shadow: 0 6px 20px rgba(0,0,0,0.08); /* Soft shadow */
        }

        h1 {
            text-align: center;
            color: #2c3e50; /* Dark blue-grey for main heading */
            margin-bottom: 40px;
            font-size: 2.8em; /* Larger font size */
            font-weight: 700; /* Bolder font weight */
            border-bottom: 2px solid #ececec; /* Subtle underline */
            padding-bottom: 20px;
        }

        .hotel-entry {
            background-color: #fcfcfc; /* Slightly off-white for individual entries */
            border-radius: 10px; /* Rounded corners */
            box-shadow: 0 3px 10px rgba(0,0,0,0.06); /* Lighter shadow */
            margin-bottom: 35px;
            padding: 25px;
            transition: transform 0.2s ease-in-out, box-shadow 0.2s ease-in-out; /* Smooth transition on hover */
            border: 1px solid #e9e9e9; /* Light border */
        }

        .hotel-entry:hover {
            transform: translateY(-7px); /* Lift effect on hover */
            box-shadow: 0 8px 20px rgba(0,0,0,0.1); /* Enhanced shadow on hover */
        }

        .hotel-entry h2 {
            color: #34495e; /* Medium blue-grey for subheadings */
            margin-top: 0;
            margin-bottom: 15px;
            font-size: 1.6em;
            word-break: break-all; /* Ensures long URLs break and don't overflow */
            font-weight: 600;
        }

        .hotel-entry img {
            max-width: 100%; /* Ensure images are fully responsive */
            height: auto; /* Maintain aspect ratio */
            border-radius: 8px; /* Rounded corners for images */
            display: block; /* Ensures image takes its own line */
            margin: 20px auto; /* Center images with vertical spacing */
            box-shadow: 0 2px 8px rgba(0,0,0,0.15); /* Shadow for images */
            border: 1px solid #ddd; /* Light border for images */
        }

        .hotel-entry a {
            color: #007bff; /* Standard blue link color */
            text-decoration: none; /* No underline by default */
            font-weight: 600; /* Bolder link text */
            transition: color 0.2s ease-in-out, text-decoration 0.2s ease-in-out;
        }

        .hotel-entry a:hover {
            color: #0056b3; /* Darker blue on hover */
            text-decoration: underline; /* Underline on hover */
        }

        .no-data {
            text-align: center;
            color: #7f8c8d; /* Grey text for no data message */
            font-style: italic;
            padding: 50px;
            font-size: 1.1em;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Hotel Detail Page Screenshots</h1>
"""
    if not image_data_list:
        html_content += """
        <p class="no-data">No hotel detail page screenshots were collected. This could be due to:</p>
        <ul class="no-data" style="list-style-type: disc; text-align: left; display: inline-block;">
            <li>The input CSV file not being found or having errors.</li>
            <li>The 'webpage' column being missing or empty.</li>
            <li>Issues with the WebDriver setup (e.g., chromedriver not in PATH).</li>
            <li>The target element not being present on the webpages within the given timeout.</li>
            <li>Network issues during scraping.</li>
        </ul>
        <p class="no-data">Please check the console logs for more details.</p>
        """
    else:
        for data in image_data_list:
            if data['image_base64']: # Only display if an image was successfully scraped
                html_content += f"""
        <div class="hotel-entry">
            <h2>Source URL: <a href="{data['url']}" target="_blank">{data['url']}</a></h2>
            <img src="data:image/png;base64,{data['image_base64']}" alt="Screenshot of {data['url']}">
        </div>
        """
            else:
                html_content += f"""
        <div class="hotel-entry">
            <h2>Source URL: <a href="{data['url'] if data['url'] else '#'}">{data['url'] if data['url'] else 'N/A'}</a></h2>
            <p>No screenshot available for this URL.</p>
        </div>
                """

    html_content += """
    </div>
</body>
</html>
"""
    try:
        with open(output_html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"HTML report generated successfully at: {output_html_path}")
    except IOError as e:
        print(f"Error writing HTML file '{output_html_path}': {e}")


def generate_map_html(df, location_col, image_data_list, output_html_path="hotel_map.html"):
    """
    Generates an HTML file with an interactive Leaflet map displaying locations from the DataFrame
    using Nominatim for geocoding.
    Includes hotel URL and image in the tooltip.
    """
    if location_col not in df.columns:
        print(f"Error: The DataFrame must contain a column named '{location_col}'.")
        return

    # Create a dictionary for quick lookup of image data by original DataFrame index
    image_data_map = {item['index']: item for item in image_data_list}

    geolocator = Nominatim(user_agent="freedreams_hotel_map_generator")

    markers = []
    for index, row in df.iterrows():
        location_name = row[location_col]
        hotel_url = row.get('freedreams_webpage', 'URL Not Available') # Get URL, provide default
        image_base64 = image_data_map.get(index, {}).get('image_base64', None)

        if pd.isna(location_name) or not isinstance(location_name, str):
            print(f"Skipping row {index}: Invalid or missing location name.")
            continue

        print(f"Geocoding location ({index + 1}/{len(df)}): {location_name}")
        try:
            location = geolocator.geocode(location_name, timeout=10) # Added timeout for robustness
            if location:
                # Construct the popup HTML content
                popup_html = f"<b><a href='{hotel_url}' target='_blank'>{hotel_url}</a></b><br>"
                if image_base64:
                    popup_html += f"<img src='data:image/png;base64,{image_base64}' style='max-width:150px; height:auto; margin-top:5px;'>"
                else:
                    popup_html += "<p>No image available.</p>"

                markers.append({
                    'name': location_name,
                    'lat': location.latitude,
                    'lng': location.longitude,
                    'popup_content': popup_html # Store the full HTML for the popup
                })
                print(f"Successfully geocoded {location_name}: ({location.latitude}, {location.longitude})")
            else:
                print(f"Could not find geocoding data for {location_name}")

        except (GeocoderTimedOut, GeocoderServiceError) as e:
            print(f"Geocoding service error for {location_name}: {e}. Skipping.")
        except Exception as e:
            print(f"An unexpected error occurred during geocoding for {location_name}: {e}. Skipping.")

        # IMPORTANT: Add a delay to respect Nominatim's usage policy (usually 1 request per second)
        time.sleep(1)

    # Convert the Python list of dictionaries to a JSON string for JavaScript
    markers_json = json.dumps(markers)

    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hotel Locations Map</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
     crossorigin=""/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
     crossorigin=""></script>
    <style>
        #map {{
            height: 100vh;
            width: 100%;
        }}
        body {{
            margin: 0;
            padding: 0;
            font-family: sans-serif;
        }}
        /* Style for Leaflet popups */
        .leaflet-popup-content-wrapper {{
            border-radius: 8px;
            padding: 10px;
        }}
        .leaflet-popup-content {{
            font-size: 14px;
            line-height: 1.5;
        }}
        .leaflet-popup-content a {{
            color: #007bff;
            text-decoration: none;
            font-weight: bold;
            word-break: break-all;
        }}
        .leaflet-popup-content a:hover {{
            text-decoration: underline;
        }}
        .leaflet-popup-content img {{
            display: block;
            margin-top: 5px;
            border-radius: 4px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        }}
    </style>
</head>
<body>
    <div id="map"></div>

    <script>
        let map;
        let markersData = {markers_json}; // Pass markers data from Python

        function initMap() {{
            // Initialize the map, centered on a default location or first marker
            if (markersData.length > 0) {{
                map = L.map('map').setView([markersData[0].lat, markersData[0].lng], 5); // Set initial view to first marker
            }} else {{
                map = L.map('map').setView([0, 0], 2); // Default to world view if no markers
            }}

            // Add OpenStreetMap tile layer
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            }}).addTo(map);

            // Create a LatLngBounds object to include all markers
            let bounds = new L.LatLngBounds();

            markersData.forEach(markerData => {{
                let marker = L.marker([markerData.lat, markerData.lng]).addTo(map)
                    .bindPopup(markerData.popup_content); // Bind popup with the generated HTML content

                // Extend bounds for each marker
                bounds.extend([markerData.lat, markerData.lng]);
            }});

            // Fit the map to the bounds of all markers, but only if there are markers
            if (markersData.length > 0) {{
                map.fitBounds(bounds);

                // If there's only one marker, set a sensible zoom level
                if (markersData.length === 1) {{
                    map.setZoom(10); // Adjust zoom as needed for a single marker
                }}
            }}
        }}

        // Call initMap when the page loads
        document.addEventListener('DOMContentLoaded', initMap);
    </script>
</body>
</html>
    """
    try:
        with open(output_html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"Leaflet Map HTML generated successfully at: {output_html_path}")
    except IOError as e:
        print(f"Error writing Leaflet Map HTML file '{output_html_path}': {e}")


def main():
    # Setup argument parser to accept the input CSV file path
    parser = argparse.ArgumentParser(description="Scrape hotel detail page images and generate a map from a CSV of URLs.")
    parser.add_argument("--input-file", type=str, required=True,
                        help="Path to the input CSV file containing hotel data (including URLs and locations).")
    parser.add_argument("--output-screenshots-html-path", type=str, default="hotel_screenshots.html",
                        help="Path to save the generated HTML report for screenshots. Default is 'hotel_screenshots.html'.")
    parser.add_argument("--output-map-html-path", type=str, default="hotel_map.html",
                        help="Path to save the generated HTML report for the map. Default is 'hotel_map.html'.")
    args = parser.parse_args()

    try:
        df = pd.read_csv(args.input_file)
    except FileNotFoundError:
        print(f"Error: The input CSV file '{args.input_file}' was not found.")
        return
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return

    # Define the output HTML file names
    output_screenshots_html_file = Path.cwd() / args.output_screenshots_html_path
    output_map_html_file = Path.cwd() / args.output_map_html_path

    if not output_map_html_file.parent.exists():
        print(f"Creating directory for output map HTML: {output_map_html_file.parent}")
        output_map_html_file.parent.mkdir(parents=True, exist_ok=True)

    # Scrape images and get the list of data
    scraped_images = scrape_hotel_images(df)

    # Generate the HTML report for screenshots
    generate_html_report(scraped_images, output_screenshots_html_file)

    # Generate the interactive Leaflet Map HTML, passing the scraped_images list
    generate_map_html(df, 'freedreams_location', scraped_images, output_map_html_file)


if __name__ == "__main__":
    main()
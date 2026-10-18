import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import argparse
import html
from pathlib import Path
import json
import time # Import time for delays
from webdriver_manager.chrome import ChromeDriverManager

# Import Nominatim for geocoding
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

GEOCODE_CACHE_PATH = Path.cwd() / ".cache" / "geocode_cache.json"


def load_geocode_cache():
    """Returns {location_name: [lat, lng]} from previous runs. Place names rarely move, so this is safe to reuse."""
    try:
        return json.loads(GEOCODE_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_geocode_cache(cache):
    GEOCODE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    GEOCODE_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


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


# Screenshots are embedded as base64 in the HTML files. Full-page PNGs of ~470 KB each made the maps 7-11 MB,
# so cropped JPEGs are used, and the map popups get a small thumbnail captured at reduced scale.
FULL_JPEG_QUALITY = 80
THUMB_JPEG_QUALITY = 70
THUMB_WIDTH_PX = 520  # displayed at ~260 CSS px: 2x for sharp rendering on phone screens


# The detail page is ~3000 px tall (calendar, long description, ...). Only the top is interesting:
# title with hotel stars, address, photo, price/meals and the guest rating.
CROP_HEIGHT_PX = 720
CROP_TOP_SELECTOR = ".s-headline-row"


def capture_element_jpeg(driver, element, quality, target_width=None):
    """
    Captures the top part of an element (from its title row, CROP_HEIGHT_PX tall) as base64 JPEG via the
    DevTools protocol, optionally scaled down to target_width.
    """
    rect = driver.execute_script(
        "const el = arguments[0], selector = arguments[1];"
        "const box = el.getBoundingClientRect();"
        "const title = el.querySelector(selector);"
        "const top = Math.max(box.top, title ? title.getBoundingClientRect().top - 15 : box.top);"
        "return {x: box.left + window.scrollX, y: top + window.scrollY, width: box.width,"
        "        height: box.bottom - top};",
        element, CROP_TOP_SELECTOR,
    )
    rect["height"] = min(rect["height"], CROP_HEIGHT_PX)
    scale = min(1.0, target_width / rect["width"]) if target_width else 1.0
    result = driver.execute_cdp_cmd("Page.captureScreenshot", {
        "format": "jpeg",
        "quality": quality,
        "captureBeyondViewport": True,
        "clip": {**rect, "scale": scale},
    })
    return result["data"]


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
                'thumb_base64': None,
                'index': index # Store original index for merging
            })
            continue

        print(f"Processing URL ({index + 1}/{len(df)}): {url}")
        try:
            driver.get(url)
            wait = WebDriverWait(driver, 20)
            target_div = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, target_div_selector)))
            image_data_list.append({
                'url': url,
                'image_base64': capture_element_jpeg(driver, target_div, FULL_JPEG_QUALITY),
                'thumb_base64': capture_element_jpeg(driver, target_div, THUMB_JPEG_QUALITY, THUMB_WIDTH_PX),
                'index': index # Store original index for merging
            })
            print(f"Successfully scraped image for {url}")

        except TimeoutException:
            print(f"Timeout: The target element was not found on page for {url}. Skipping.")
            image_data_list.append({
                'url': url,
                'image_base64': None, # No image if timeout
                'thumb_base64': None,
                'index': index
            })
        except WebDriverException as e:
            print(f"WebDriver error occurred while processing {url}: {e}. Skipping.")
            image_data_list.append({
                'url': url,
                'image_base64': None,
                'thumb_base64': None,
                'index': index
            })
        except Exception as e:
            print(f"An unexpected error occurred for {url}: {e}. Skipping.")
            image_data_list.append({
                'url': url,
                'image_base64': None,
                'thumb_base64': None,
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
            <img src="data:image/jpeg;base64,{data['image_base64']}" alt="Screenshot of {data['url']}">
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


def build_popup_html(row, hotel_url, thumb_base64, restaurants, status_entry=None):
    """HTML of a map popup: hotel name, stars and rating as text (readable at any size), restaurants, thumbnail."""
    name = row.get('freedreams_hotel_name')
    name = name if isinstance(name, str) and name else hotel_url
    html_parts = [f"<b><a href='{html.escape(str(hotel_url), quote=True)}' target='_blank'>{html.escape(name)}</a></b>"]

    meta = []
    try:
        num_stars = int(float(row.get('freedreams_num_stars')))
    except (TypeError, ValueError):
        num_stars = 0
    if num_stars > 0:
        meta.append("★" * num_stars)
    rating = row.get('freedreams_rating')
    if isinstance(rating, str) and rating and rating != "No rating":
        meta.append(html.escape(rating))
    if meta:
        html_parts.append(f"<div class='meta'>{' · '.join(meta)}</div>")

    if status_entry:
        style = STATUS_STYLE[status_entry["status"]]
        html_parts.append(f"<div class='status' style='color:{style['color']}'>● {html.escape(style['label'])}</div>")
        if status_entry.get("note"):
            html_parts.append(f"<div class='note'>{html.escape(status_entry['note'])}</div>")

    themes = row.get('freedreams_themes')
    themes = [t for t in str(themes).split("|")] if isinstance(themes, str) else []
    flags = "".join(
        f"<span title='{html.escape(THEME_FLAGS[t][1], quote=True)}'>{THEME_FLAGS[t][0]}</span>"
        for t in THEME_FLAGS if t in themes
    )
    if flags:
        html_parts.append(f"<div class='flags'>{flags}</div>")

    for restaurant in restaurants:
        note = " <i>(address differs)</i>" if restaurant.get('match') == 'name_same_zip' else ""
        address = f" – {html.escape(restaurant['address'])}" if restaurant.get('address') else ""
        html_parts.append(f"<div class='restaurant'>🍽 {html.escape(restaurant['name'])}{address}{note}</div>")

    if thumb_base64:
        html_parts.append(f"<img src='data:image/jpeg;base64,{thumb_base64}' alt=''>")
    return "".join(html_parts)


# Hotel status (which hotels were visited / replied / rejected) is kept by hand in hotel_status.json.
# It only colours hotels that are in the current matches: a hotel that is no longer offered is not drawn at all.
# Hotels without an entry are "unknown" (grey). Entries are matched by Freedreams URL, or by a name/location
# pattern, so a hotel that disappears from Freedreams and comes back (possibly under a new URL) keeps its status.
STATUS_STYLE = {
    "stayed": {"color": "#16a34a", "label": "Stayed here"},
    "positive": {"color": "#eab308", "label": "Replied positively, not stayed"},
    "rejected": {"color": "#dc2626", "label": "Rejected (combo not possible)"},
    "unknown": {"color": "#9ca3af", "label": "No info yet"},
}
DEFAULT_STATUS_PATH = "hotel_status.json"

# Freedreams "Themen" of a hotel -> emoji flag in the map popup (and its tooltip). Change the emoji here.
THEME_FLAGS = {
    "WANDERN": ("🥾", "Hiking"),
    "WINTERSPORT": ("⛷️", "Winter sports"),
    "WELLNESS": ("🧖", "Wellness / spa"),
    "ÖV-FREUNDLICH": ("🚆", "Easy by public transport"),
}


def load_hotel_status(path):
    """Returns the list of status entries; an absent or broken file just means no statuses."""
    try:
        entries = json.loads(Path(path).read_text(encoding="utf-8")).get("hotels", [])
    except (OSError, ValueError) as e:
        print(f"No hotel status loaded from {path}: {e}")
        return []
    for entry in entries:
        if entry.get("status") not in STATUS_STYLE:
            print(f"Warning: unknown status {entry.get('status')!r} for {entry.get('name')!r}; treating as 'unknown'.")
            entry["status"] = "unknown"
    return entries


def find_status_entry(entries, hotel_url, hotel_name="", hotel_location=""):
    """The status entry for a hotel, matched by URL first and then by its name/location pattern."""
    for entry in entries:
        if hotel_url in entry.get("urls", []):
            return entry
    name, location = str(hotel_name).lower(), str(hotel_location).lower()
    for entry in entries:
        pattern = entry.get("match")
        if pattern and pattern.get("name_contains", "").lower() in name and \
                pattern.get("location_contains", "").lower() in location and (name or location):
            return entry
    return None


def restaurant_coordinates(restaurants):
    """First valid (lat, lng) of the matched restaurants, or None."""
    for restaurant in restaurants:
        try:
            lat, lng = float(restaurant.get('lat')), float(restaurant.get('lng'))
        except (TypeError, ValueError):
            continue
        if lat == lat and lng == lng:   # not NaN
            return lat, lng
    return None


def geocode_location(geolocator, geocode_cache, location_name):
    """(lat, lng) of a place name via the cache or Nominatim; None if it cannot be resolved."""
    cached = geocode_cache.get(location_name)
    if cached:
        return tuple(cached)
    try:
        location = geolocator.geocode(location_name, timeout=10)
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        print(f"Geocoding service error for {location_name}: {e}. Skipping.")
        time.sleep(1)
        return None
    except Exception as e:
        print(f"An unexpected error occurred during geocoding for {location_name}: {e}. Skipping.")
        time.sleep(1)
        return None

    # IMPORTANT: Add a delay to respect Nominatim's usage policy (usually 1 request per second).
    # Only needed after a real request, not for cache hits.
    time.sleep(1)
    if not location:
        print(f"Could not find geocoding data for {location_name}")
        return None
    geocode_cache[location_name] = [location.latitude, location.longitude]
    print(f"Successfully geocoded {location_name}: ({location.latitude}, {location.longitude})")
    return location.latitude, location.longitude


def generate_map_html(df, location_col, image_data_list, output_html_path="hotel_map.html", restaurants_by_url=None,
                      status_entries=None):
    """
    Generates an HTML file with an interactive Leaflet map displaying locations from the DataFrame
    using Nominatim for geocoding.
    Includes hotel name, stars/rating, the matched restaurants and a thumbnail in the popup.

    df must contain one row per hotel; restaurants_by_url maps a hotel URL to its matched restaurants.
    """
    if location_col not in df.columns:
        print(f"Error: The DataFrame must contain a column named '{location_col}'.")
        return

    # Create a dictionary for quick lookup of image data by original DataFrame index
    image_data_map = {item['index']: item for item in image_data_list}

    geolocator = Nominatim(user_agent="freedreams_hotel_map_generator")

    status_entries = status_entries or []
    geocode_cache = load_geocode_cache()
    markers = []
    for index, row in df.iterrows():
        location_name = row[location_col]
        hotel_url = row.get('freedreams_webpage', 'URL Not Available') # Get URL, provide default
        thumb_base64 = image_data_map.get(index, {}).get('thumb_base64', None)

        if pd.isna(location_name) or not isinstance(location_name, str):
            print(f"Skipping row {index}: Invalid or missing location name.")
            continue

        restaurants = (restaurants_by_url or {}).get(hotel_url, [])
        exact_position = restaurant_coordinates(restaurants)
        # Lunch-Check knows the exact position of the matched restaurant, which is at the hotel
        position = exact_position or geocode_location(geolocator, geocode_cache, location_name)
        if not position:
            continue
        lat, lng = position
        status_entry = find_status_entry(status_entries, hotel_url, row.get('freedreams_hotel_name', ''), location_name)

        popup_html = build_popup_html(row, hotel_url, thumb_base64, restaurants, status_entry)

        markers.append({
            'name': location_name,
            'lat': lat,
            'lng': lng,
            'popup_content': popup_html, # Store the full HTML for the popup
            'status': (status_entry or {}).get('status', 'unknown'),
        })

    save_geocode_cache(geocode_cache)

    # Convert the Python list of dictionaries to a JSON string for JavaScript
    markers_json = json.dumps(markers)
    stacking = {"stayed": 300, "positive": 200, "rejected": 100, "unknown": 0}
    status_style_json = json.dumps({
        status: {**style, "z": stacking[status]} for status, style in STATUS_STYLE.items()
    })

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
        .leaflet-popup-content .meta {{
            color: #b45309;
            font-weight: 600;
        }}
        .leaflet-popup-content .flags {{
            font-size: 20px;
            letter-spacing: 4px;
            margin-top: 2px;
        }}
        .leaflet-popup-content .status {{
            font-weight: 600;
            margin-top: 2px;
        }}
        .leaflet-popup-content .note {{
            font-size: 12px;
            color: #555;
            margin-top: 2px;
        }}
        .legend {{
            background: rgba(255,255,255,0.92);
            padding: 6px 10px;
            border-radius: 8px;
            font-size: 12px;
            line-height: 1.7;
            box-shadow: 0 1px 5px rgba(0,0,0,0.3);
        }}
        .legend i {{
            display: inline-block;
            width: 11px;
            height: 11px;
            border-radius: 50%;
            margin-right: 6px;
            vertical-align: -1px;
        }}
        .leaflet-popup-content .restaurant {{
            font-size: 13px;
            color: #333;
            margin-top: 2px;
        }}
        .leaflet-popup-content img {{
            display: block;
            width: 260px;
            max-width: 100%;
            height: auto;
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
        const statusStyle = {status_style_json}; // colour, label and stacking order per status

        function pinIcon(color) {{
            return L.divIcon({{
                className: '',
                html: '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="40" viewBox="0 0 28 40">' +
                      '<path d="M14 1C7 1 1.5 6.5 1.5 13.5C1.5 23 14 39 14 39S26.5 23 26.5 13.5C26.5 6.5 21 1 14 1Z" ' +
                      'fill="' + color + '" stroke="#fff" stroke-width="2"/><circle cx="14" cy="13.5" r="4.5" fill="#fff"/></svg>',
                iconSize: [28, 40],
                iconAnchor: [14, 39],
                popupAnchor: [0, -34]
            }});
        }}

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

            // Legend
            const legend = L.control({{position: 'bottomleft'}});
            legend.onAdd = () => {{
                const div = L.DomUtil.create('div', 'legend');
                div.innerHTML = Object.values(statusStyle)
                    .map(s => '<div><i style="background:' + s.color + '"></i>' + s.label + '</div>').join('');
                return div;
            }};
            legend.addTo(map);

            // Create a LatLngBounds object to include all markers
            let bounds = new L.LatLngBounds();

            markersData.forEach(markerData => {{
                let marker = L.marker([markerData.lat, markerData.lng], {{
                    icon: pinIcon(statusStyle[markerData.status].color),
                    zIndexOffset: statusStyle[markerData.status].z
                }}).addTo(map)
                    .bindPopup(markerData.popup_content, {{maxWidth: 300}}); // Bind popup with the generated HTML content

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
    parser.add_argument("--status-file", type=str, default=DEFAULT_STATUS_PATH,
                        help="JSON file with the visited/replied/rejected status of hotels. Default is 'hotel_status.json'.")
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

    # Several restaurants can match the same hotel: scrape and plot every hotel only once.
    restaurants_by_url = {}
    for _, row in df.iterrows():
        restaurants_by_url.setdefault(row['freedreams_webpage'], []).append({
            'name': row.get('lunchcheck_restaurant_name'),
            'address': row.get('lunchcheck_address') if isinstance(row.get('lunchcheck_address'), str) else '',
            'match': row.get('Address_Match'),
            'lat': row.get('lunchcheck_latitude'),
            'lng': row.get('lunchcheck_longitude'),
        })
    hotels_df = df.drop_duplicates(subset='freedreams_webpage').reset_index(drop=True)

    # Scrape images and get the list of data
    scraped_images = scrape_hotel_images(hotels_df)

    # Generate the HTML report for screenshots
    generate_html_report(scraped_images, output_screenshots_html_file)

    # Generate the interactive Leaflet Map HTML, passing the scraped_images list
    generate_map_html(hotels_df, 'freedreams_location', scraped_images, output_map_html_file, restaurants_by_url,
                      load_hotel_status(Path.cwd() / args.status_file))


if __name__ == "__main__":
    main()
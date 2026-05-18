import os
import random
import time
import urllib.parse
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


DEBUG_DUMP = os.getenv("DEBUG_DUMP", "").lower() in ("1", "true", "yes")
SCRAPER_HEADLESS = os.getenv("SCRAPER_HEADLESS", "true").lower() in ("1", "true", "yes")
PROXY = os.getenv("SCRAPER_PROXY", "").strip()
MAX_RETRIES = int(os.getenv("SCRAPER_MAX_RETRIES", "3"))
TWO_CAPTCHA_API_KEY = os.getenv("TWO_CAPTCHA_API_KEY", "").strip()

# Bright Data Residential Proxy
BRIGHTDATA_ZONE = os.getenv("BRIGHTDATA_ZONE", "").strip()
BRIGHTDATA_USERNAME = os.getenv("BRIGHTDATA_USERNAME", "").strip()
BRIGHTDATA_PASSWORD = os.getenv("BRIGHTDATA_PASSWORD", "").strip()


def get_proxy_url():
    """Build proxy URL from Bright Data credentials or manual proxy."""
    import urllib.parse
    if BRIGHTDATA_ZONE and BRIGHTDATA_USERNAME and BRIGHTDATA_PASSWORD:
        # URL encode the password to handle special characters like #
        encoded_password = urllib.parse.quote(BRIGHTDATA_PASSWORD, safe='')
        return f"http://{BRIGHTDATA_USERNAME}-{BRIGHTDATA_ZONE}:{encoded_password}@brd.superproxy.io:33335"
    elif PROXY:
        return PROXY
    return ""


def solve_recaptcha(driver, log_callback, max_wait=120):
    """Solve reCAPTCHA using 2Captcha service."""
    if not TWO_CAPTCHA_API_KEY:
        log_callback("No 2Captcha API key configured.")
        return None

    try:
        # Find the reCAPTCHA iframe and get the sitekey
        sitekey = None
        recaptcha_iframes = driver.find_elements(By.XPATH, "//iframe[contains(@src, 'recaptcha')]")
        for iframe in recaptcha_iframes:
            src = iframe.get_attribute("src")
            if "sitekey=" in src:
                sitekey = src.split("sitekey=")[1].split("&")[0]
                break

        # Also try to find sitekey from data-sitekey attribute
        data_s = None
        sitekey_elem = driver.find_elements(By.XPATH, "//div[@class='g-recaptcha']")
        if sitekey_elem:
            if not sitekey:
                sitekey = sitekey_elem[0].get_attribute("data-sitekey")
            data_s = sitekey_elem[0].get_attribute("data-s")

        if not sitekey:
            log_callback("Could not find reCAPTCHA sitekey.")
            return None

        log_callback(f"Found reCAPTCHA sitekey: {sitekey[:20]}...")

        # Submit to 2Captcha
        log_callback("Submitting reCAPTCHA to 2Captcha...")
        submit_url = "http://2captcha.com/in.php"
        submit_data = {
            "key": TWO_CAPTCHA_API_KEY,
            "method": "userrecaptcha",
            "googlekey": sitekey,
            "pageurl": driver.current_url,
            "json": 1,
            "enterprise": 1
        }
        if data_s:
            submit_data["data-s"] = data_s
            log_callback(f"Found and including data-s: {data_s[:20]}...")

        resp = requests.post(submit_url, data=submit_data, timeout=30)
        result = resp.json()

        if result.get("status") != 1:
            log_callback(f"2Captcha submit failed: {result}")
            return None

        task_id = result.get("request")
        log_callback(f"2Captcha task ID: {task_id}")

        # Poll for result
        log_callback("Waiting for 2Captcha to solve...")
        poll_url = "http://2captcha.com/res.php"
        for i in range(max_wait // 5):
            time.sleep(5)
            try:
                poll_resp = requests.get(poll_url, params={
                    "key": TWO_CAPTCHA_API_KEY,
                    "action": "get",
                    "id": task_id,
                    "json": 1
                }, timeout=30)
                poll_result = poll_resp.json()

                if poll_result.get("status") == 1:
                    captcha_solution = poll_result.get("request")
                    log_callback("reCAPTCHA solved! Submitting token...")

                    # Try multiple methods to set the token
                    try:
                        # Method 1: Set value on textarea
                        textarea = driver.find_element(By.CSS_SELECTOR, "textarea[name='g-recaptcha-response']")
                        driver.execute_script("arguments[0].style.display = 'block';", textarea)
                        driver.execute_script(f"arguments[0].value = '{captcha_solution}';", textarea)
                        driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", textarea)
                        driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", textarea)
                    except Exception as e:
                        log_callback(f"Token injection method 1 failed: {e}")

                    # Method 2: Also try setting via innerHTML on any element with that name
                    driver.execute_script(f'''
                        var el = document.querySelector('[name="g-recaptcha-response"]');
                        if (el) {{ el.innerHTML = "{captcha_solution}"; }}
                    ''')

                    # Submit the captcha form
                    try:
                        driver.execute_script('''
                            var solution = arguments[0];
                            if (typeof submitCallback === 'function') {
                                submitCallback(solution);
                            } else {
                                var form = document.getElementById('captcha-form') || document.querySelector('form');
                                if (form) {
                                    form.submit();
                                }
                            }
                        ''', captcha_solution)
                        log_callback("Form submitted successfully!")
                    except Exception as e:
                        log_callback(f"Failed to submit form via JS: {e}")

                    time.sleep(5)
                    return captcha_solution
                elif poll_result.get("request") == "CAPCHA_NOT_READY":
                    log_callback(f"Still waiting... ({i+1}/{max_wait//5})")
                else:
                    log_callback(f"2Captcha error: {poll_result}")
                    break
            except Exception as e:
                log_callback(f"Poll error: {e}")

        log_callback("2Captcha solve timed out.")
        return None

    except Exception as e:
        log_callback(f"reCAPTCHA solve error: {e}")
        return None


def get_driver():
    import undetected_chromedriver as uc

    options = uc.ChromeOptions()
    if SCRAPER_HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=ja")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-images")
    options.add_argument("--disable-blink-features=AutomationControlled")

    # More realistic browser behavior (compatible with older Chrome)
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-hang-monitor")
    options.add_argument("--disable-ipc-flooding-protection")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-client-side-phishing-detection")
    options.add_argument("--disable-low-res-tiling")
    options.add_argument("--log-level=3")
    options.add_argument("--silent")

    options.add_experimental_option("prefs", {
        "intl.accept_languages": "ja,ja-JP",
        "profile.default_content_settings.geolocation": 1,
        "profile.default_content_setting_values.notifications": 2,
        "profile.default_content_setting_values.images": 2,
    })

    # Rotate user agents to avoid fingerprinting
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    ]
    ua = random.choice(user_agents)
    options.add_argument(f"--user-agent={ua}")

    # Use Bright Data or manual proxy
    proxy_url = get_proxy_url()
    if proxy_url:
        log_callback(f"Using proxy: {proxy_url.split('@')[0]}@***")  # Hide password in log
        options.add_argument(f"--proxy-server={proxy_url}")

    options.binary_location = "/usr/bin/chromium"

    driver = uc.Chrome(
        options=options,
        driver_executable_path="/usr/bin/chromedriver",
        browser_executable_path="/usr/bin/chromium",
    )

    # Anti-detection: patch webdriver property
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['ja', 'ja-JP', 'en-US', 'en']
            });
            window.chrome = { runtime: {} };
        """
    })

    return driver


def save_debug(driver, label):
    if not DEBUG_DUMP:
        return
    timestamp = int(time.time())
    html_path = f"/tmp/debug_{label}_{timestamp}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print(f"[DEBUG] Page source saved to {html_path}")
    
    try:
        png_path = f"/tmp/debug_{label}_{timestamp}.png"
        driver.save_screenshot(png_path)
        print(f"[DEBUG] Screenshot saved to {png_path}")
    except Exception as e:
        print(f"[DEBUG] Failed to save screenshot: {e}")


def has_product_section(driver, log_callback=None):
    """Check if the page has a product catalog section (not just posts/services)."""
    indicators = [
        "//*[@data-attrid='kc:/local:products_overview_for_desktop']",
        "//*[@data-attrid='kc:/local:product catalog']",
        "//*[@data-attrid='kc:/local:products']",
        "//*[contains(@data-attrid, 'products_overview')]",
        "//*[contains(@data-attrid, 'product')]",
        "//*[contains(@data-attrid, 'product')]//div[contains(@class, 'BFOCWc')]",
        "//*[contains(@data-attrid, 'product')]//span[contains(@class, 'OSrXXb')]",
        "//*[contains(@class, 'sh-pr')]",
        "//a[contains(@href, '/lpc/')]",
        "//*[@data-product-to-scroll]",
        "//a[contains(@data-href, '/local/place/products/product')]",
        "//div[contains(@class, 't3RpAe')]",
    ]
    for xpath in indicators:
        elements = driver.find_elements(By.XPATH, xpath)
        if elements:
            if log_callback:
                log_callback(f"Product section indicator matched: {xpath}")
            return True

    # Fallback: look for elements containing "商品" (products) text
    product_text_elements = driver.find_elements(By.XPATH, "//span[contains(., '商品')]")
    if product_text_elements:
        for el in product_text_elements:
            text = el.text.strip()
            if text and len(text) < 50:  # Skip long paragraphs
                if log_callback:
                    log_callback(f"Product section fallback text matched: '{text}'")
                return True
    return False


def find_product_show_all(driver, log_callback=None):
    """Find 'Show all' button specifically inside a product section."""
    # First look for product-scoped show-all
    product_scope = [
        "//*[@data-attrid='kc:/local:products_overview_for_desktop']//*[text()='すべて表示']",
        "//*[@data-attrid='kc:/local:products_overview_for_desktop']//*[contains(text(), 'すべて')]",
        "//*[@data-attrid='kc:/local:product catalog']//*[text()='すべて表示']",
        "//*[@data-attrid='kc:/local:product catalog']//*[contains(text(), 'すべて')]",
        "//*[contains(@data-attrid, 'products_overview')]//*[text()='すべて表示']",
        "//*[contains(@data-attrid, 'products_overview')]//*[contains(text(), 'すべて')]",
        "//*[contains(@data-attrid, 'product')]//*[text()='すべて表示']",
        "//*[contains(@data-attrid, 'product')]//*[contains(text(), 'すべて')]",
        "//div[contains(@class, 'BFOCWc')]/ancestor::*[@data-hveid]//*[contains(text(), 'すべて')]",
        "//a[contains(text(), 'すべて表示') and ancestor::*[.//a[contains(@data-href, '/local/place/products/product')]]]",
        "//a[contains(text(), 'すべて表示') and ancestor::*[.//*[contains(@class, 'prDW') or contains(@class, 't3RpAe')]]]",
    ]
    for xpath in product_scope:
        try:
            btn = driver.find_element(By.XPATH, xpath)
            if btn and btn.is_displayed():
                if log_callback:
                    log_callback(f"Found 'Show all' button via scoped match: {xpath}")
                return btn, f"product-section: {xpath[:60]}"
        except Exception:
            continue

    # Broader: any show-all that is near product-related content
    general = [
        ("//*[text()='すべての商品を表示']", "exact 'すべての商品を表示'"),
        ("//*[contains(text(), 'すべての商品')]", "contains 'すべての商品'"),
        ("//*[text()='すべて表示'][ancestor::div[contains(., '商品')]]", "すべて表示 near 商品 text"),
        ("//*[@aria-label='すべて表示'][contains(@href, 'product')]", "aria-label + product href"),
        ("//a[contains(@href, 'products')][contains(text(), 'すべて')]", "href products + すべて"),
        ("//a[contains(@href, 'lpc')][contains(text(), 'すべて')]", "href lpc + すべて"),
        ("//a[contains(text(), 'すべて表示')]", "any a tag with すべて表示"),
        ("//*[contains(text(), 'すべて表示')]", "any element with すべて表示"),
    ]
    for xpath, desc in general:
        try:
            btn = driver.find_element(By.XPATH, xpath)
            if btn and btn.is_displayed():
                if log_callback:
                    log_callback(f"Found 'Show all' button via broader match: {desc} ({xpath})")
                return btn, desc
        except Exception:
            continue

    return None, None


def handle_local_pack(driver, store_name, log_callback):
    """Check if a local pack is shown, and if so, click the matching business to open its Knowledge Panel."""
    pack_items = driver.find_elements(By.XPATH, "//div[contains(@class, 'dbg0pd')]")
    if not pack_items:
        log_callback("No local pack found. Treating current page as direct Knowledge Panel...")
        return False
        
    log_callback(f"Local pack detected with {len(pack_items)} items. Looking for matching business...")
    
    for item in pack_items:
        try:
            text = item.text.strip()
            if text and store_name in text:
                log_callback(f"Found matching business in local pack: '{text}'. Preparing to open its Knowledge Panel...")
                log_callback(f"Scrolling matching business '{text}' into view...")
                driver.execute_script("arguments[0].scrollIntoView(true);", item)
                time.sleep(1)
                
                log_callback(f"Clicking on business '{text}' in local pack...")
                driver.execute_script("arguments[0].click();", item)
                
                log_callback("Waiting for the Knowledge Panel content to load...")
                time.sleep(random.uniform(4, 6))
                
                log_callback("Scrolling page down to trigger lazy loading of product/service catalog carousels...")
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
                time.sleep(1.5)
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                
                log_callback(f"Checking if '{text}' has a Product Catalog section...")
                if has_product_section(driver, log_callback):
                    log_callback("Product section successfully found and validated for this business!")
                    return True
                else:
                    log_callback("No product section found for this business. Trying next match if any...")
        except Exception as e:
            log_callback(f"Error handling local pack item: {e}")
            continue
            
    log_callback("Finished checking local pack items.")
    return False


def extract_product_names(driver, log_callback=None):
    """Extract product names from the currently visible page/modal."""
    strategies = [
        # Products overview for desktop (current Google structure)
        "//*[@data-attrid='kc:/local:products_overview_for_desktop']//a",
        "//*[@data-attrid='kc:/local:products_overview_for_desktop']//span",
        "//*[@data-attrid='kc:/local:products_overview_for_desktop']//div[contains(@class, 'Gik6Zd')]",
        "//*[@data-attrid='kc:/local:products_overview_for_desktop']//span[contains(@class, 'OSrXXb')]",
        # Explicit data attribute for products
        "//*[@data-product-to-scroll]",
        # Product catalog section items
        "//div[@data-attrid='kc:/local:product catalog']//a",
        "//div[@data-attrid='kc:/local:product catalog']//span",
        "//*[contains(@data-attrid, 'products_overview')]//div[contains(@class, 'Gik6Zd')]",
        "//*[contains(@data-attrid, 'products_overview')]//span[contains(@class, 'OSrXXb')]",
        # Product names in carousel restricted
        "//*[contains(@data-attrid, 'product')]//div[contains(@class, 'Gik6Zd')]",
        "//*[contains(@data-attrid, 'product')]//span[contains(@class, 'OSrXXb')]",
        "//g-scrolling-carousel//span[contains(@class, 'OSrXXb')]",
        "//div[@role='dialog']//span[contains(@class, 'OSrXXb')]",
        "//div[@role='dialog']//div[contains(@class, 'Gik6Zd')]",
        # Product cards restricted
        "//*[contains(@data-attrid, 'product')]//div[contains(@class, 'BFOCWc')]//span",
        "//div[@role='dialog']//div[contains(@class, 'BFOCWc')]//span",
        # Side panel / lpc (local product catalog)
        "//div[contains(@class, 'lpc')]//span",
        "//div[contains(@id, 'lpc')]//span",
        # Generic product elements in dialog or carousel
        "//g-scrolling-carousel//span[string-length(normalize-space())>1]",
        "//div[@role='dialog']//span[string-length(normalize-space())>1]",
        # Direct product classes based on observation
        "//div[contains(@class, 't3RpAe')]",
        "//a[contains(@data-href, '/local/place/products/product')]//div[contains(@class, 't3RpAe')]",
        "//div[contains(@class, 'su7Prc')]//div[contains(@class, 't3RpAe')]",
    ]
    seen = set()
    for selector in strategies:
        items = driver.find_elements(By.XPATH, selector)
        if items and log_callback:
            log_callback(f"Checking xpath strategy '{selector}' - found {len(items)} elements...")
        for item in items:
            text = item.text.strip()
            if text:
                text = text.split('\n')[0].strip()
            if text and text not in seen:
                seen.add(text)
                if log_callback:
                    log_callback(f"Successfully extracted product name: '{text}'")
        if seen:
            return list(seen)
    return []


def extract_service_names(driver, log_callback=None):
    """Extract service/category names for service businesses."""
    strategies = [
        "//div[contains(@class, 'sB1Bee')]",
        "//div[@data-attrid='kc:/local:service catalog']//span",
        "//div[@data-attrid='kc:/local:service']//a",
        "//div[@role='listitem']//span[contains(@class, 'OSrXXb')]",
        "//div[contains(@class, 'r6BRBd')]//div[contains(@class, 'hvddEd')]//div",
    ]
    seen = set()
    for selector in strategies:
        items = driver.find_elements(By.XPATH, selector)
        if items and log_callback:
            log_callback(f"Checking service catalog strategy '{selector}' - found {len(items)} elements...")
        for item in items:
            text = item.text.strip()
            if text and text not in seen:
                seen.add(text)
                if log_callback:
                    log_callback(f"Successfully extracted fallback service name: '{text}'")
        if seen:
            return list(seen)
    return []


def _scrape_attempt(store_name: str, log_callback) -> tuple[dict, object]:
    """Single scrape attempt. Returns (result_dict, driver)."""
    driver = get_driver()
    result = {
        "store_name": store_name,
        "product_count": 0,
        "products": [],
        "error": None,
    }

    try:
        encoded_query = urllib.parse.quote(store_name)
        # Add extra params to reduce reCAPTCHA likelihood
        url = f"https://www.google.co.jp/search?q={encoded_query}&hl=ja&gl=jp&tbs=isz:l"
        log_callback(f"Navigating to Google search for '{store_name}'...")

        driver.get(url)

        # Human-like: wait for initial page load with random delay
        time.sleep(random.uniform(3, 6))

        # Human-like: gradual scroll down (not instant)
        for i in range(1, 4):
            driver.execute_script(f"window.scrollTo(0, {i * 150});")
            time.sleep(random.uniform(0.3, 0.7))

        # Small pause at bottom
        time.sleep(random.uniform(0.5, 1.0))

        # Scroll back up slightly (human behavior)
        driver.execute_script("window.scrollTo(0, 100);")
        time.sleep(random.uniform(0.5, 1.0))

        save_debug(driver, "initial_page")

        page_source = driver.page_source.lower()
        if "recaptcha" in page_source or "unusual traffic" in page_source:
            result["_recaptcha"] = True
            log_callback("ERROR: reCAPTCHA page detected - Google blocked the request")

            # Try to solve with 2Captcha if API key is available
            if TWO_CAPTCHA_API_KEY:
                log_callback("Attempting to solve reCAPTCHA with 2Captcha...")
                token = solve_recaptcha(driver, log_callback)
                if token:
                    log_callback("reCAPTCHA solved! Checking if redirect occurred...")
                    time.sleep(3)

                    # Check if page loaded successfully after solve
                    new_page_source = driver.page_source.lower()
                    if "recaptcha" not in new_page_source and "unusual traffic" not in new_page_source:
                        log_callback("reCAPTCHA bypassed successfully via form redirect!")
                        result.pop("_recaptcha", None)
                    else:
                        log_callback("Still on reCAPTCHA page, navigating to search URL manually...")
                        encoded_query = urllib.parse.quote(store_name)
                        new_url = f"https://www.google.co.jp/search?q={encoded_query}&hl=ja&gl=jp&tbs=isz:l"
                        driver.get(new_url)
                        time.sleep(random.uniform(4, 7))

                        new_page_source = driver.page_source.lower()
                        if "recaptcha" not in new_page_source and "unusual traffic" not in new_page_source:
                            log_callback("reCAPTCHA bypassed successfully after manual navigation!")
                            result.pop("_recaptcha", None)
                        else:
                            log_callback("reCAPTCHA still present after manual navigation - trying to find and click submit if exists")

                        # Try to find and click any submit button in the form
                        try:
                            submit_buttons = driver.find_elements(By.XPATH, "//button[contains(@type, 'submit')]")
                            for btn in submit_buttons:
                                if btn.is_displayed():
                                    btn.click()
                                    time.sleep(3)
                                    break
                        except Exception as e:
                            log_callback(f"Could not find submit button: {e}")
                else:
                    log_callback("Failed to solve reCAPTCHA.")
            else:
                log_callback("No 2Captcha API key - cannot solve.")

            if result.get("_recaptcha"):
                result["error"] = "Google is showing reCAPTCHA due to rate-limiting. Try a different store name or use a proxy."
                save_debug(driver, "recaptcha_block")
                return result, driver

        log_callback("Checking for cookie consent dialog...")
        try:
            consent_btn = WebDriverWait(driver, 4).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(., '同意')]"))
            )
            consent_btn.click()
            log_callback("Cookie consent accepted.")
            time.sleep(1)
        except Exception:
            log_callback("No cookie consent dialog found.")

        save_debug(driver, "after_cookies")

        # Handle local pack if it exists (multiple businesses listed)
        handle_local_pack(driver, store_name, log_callback)

        has_products = has_product_section(driver, log_callback)
        log_callback(f"Product section final detection result: {has_products}")

        if has_products:
            log_callback("Looking for 'Show all' button in product section...")
            show_all_btn, strategy_desc = find_product_show_all(driver, log_callback)

            log_callback("Extracting product names before clicking 'Show all'...")
            products_before = extract_product_names(driver, log_callback)

            if show_all_btn:
                log_callback(f"Found 'Show all' button via: {strategy_desc}")
                log_callback("Scrolling to 'Show all' button...")

                # Human-like: random delay before clicking
                time.sleep(random.uniform(0.5, 1.5))

                # Scroll to the button first
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", show_all_btn)
                time.sleep(random.uniform(0.3, 0.8))

                log_callback("Clicking the 'Show all' button...")
                try:
                    show_all_btn.click()
                    log_callback("Native element click successful.")
                except Exception as e:
                    log_callback(f"Native click failed ({e}). Falling back to JavaScript click...")
                    driver.execute_script("arguments[0].click();", show_all_btn)
                    log_callback("JavaScript click executed.")

                log_callback("Waiting for product modal/section to load dynamically...")
                time.sleep(random.uniform(3, 5))
                save_debug(driver, "after_showall_click")

            log_callback("Extracting product names after clicking 'Show all'...")
            products_after = extract_product_names(driver, log_callback)

            all_products = list(set(products_before + products_after))
            if all_products:
                log_callback(f"Extracted product names list: {all_products}")

            if all_products:
                result["products"] = all_products
                result["product_count"] = len(all_products)
                log_callback(f"Done. Product count: {result['product_count']}")
                return result, driver

            save_debug(driver, "no_products_found")
            log_callback("No products extracted — checking for services fallback...")

        log_callback("Checking for service/category names as fallback...")
        services = extract_service_names(driver, log_callback)

        if services:
            result["products"] = services
            result["product_count"] = len(services)
            result["error"] = "This appears to be a service business. Showing service categories instead of products."
            log_callback(f"Extracted {len(services)} service names as fallback.")
            return result, driver

        save_debug(driver, "no_content_found")
        result["error"] = "No products or services found. Google may not show a product catalog for this business."
        log_callback("ERROR: No products or services found.")

    except Exception as e:
        result["error"] = str(e)
        log_callback(f"ERROR: {str(e)}")
        save_debug(driver, "exception")

    return result, driver


def scrape_store_products(store_name: str, log_callback=None) -> dict:
    if log_callback is None:
        log_callback = lambda msg: None

    result = None
    driver_ref = None

    for attempt in range(1, MAX_RETRIES + 1):
        log_callback(f"Attempt {attempt}/{MAX_RETRIES}...")

        this_result, driver_ref = _scrape_attempt(store_name, log_callback)

        if driver_ref:
            try:
                driver_ref.quit()
            except Exception:
                pass
            log_callback("Chrome driver closed.")

        result = this_result

        is_recaptcha = result.get("_recaptcha", False) or (
            result.get("error") and "reCAPTCHA" in str(result.get("error", ""))
        )
        if not is_recaptcha:
            break

        if attempt < MAX_RETRIES:
            # Longer delay for reCAPTCHA - wait before retrying
            delay = 5 + (2 ** attempt) * 3 + random.uniform(5, 15)
            log_callback(f"reCAPTCHA detected — retrying in {delay:.0f}s...")
            time.sleep(delay)

    result.pop("_recaptcha", None)
    return result
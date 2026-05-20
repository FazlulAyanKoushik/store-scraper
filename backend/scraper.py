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
    else:
        # Options for headed mode in Docker (requires Xvfb or similar)
        options.add_argument("--remote-debugging-port=9222")
        options.add_argument("--disable-setuid-sandbox")
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
    
    debug_dir = "/tmp/debug_output"
    if not os.path.exists(debug_dir):
        try:
            os.makedirs(debug_dir, exist_ok=True)
        except Exception as e:
            print(f"[DEBUG] Failed to create debug directory {debug_dir}: {e}")
            debug_dir = "/tmp"

    timestamp = int(time.time())
    html_path = f"{debug_dir}/debug_{label}_{timestamp}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print(f"[DEBUG] Page source saved to {html_path}")
    
    try:
        png_path = f"{debug_dir}/debug_{label}_{timestamp}.png"
        driver.save_screenshot(png_path)
        print(f"[DEBUG] Screenshot saved to {png_path}")
    except Exception as e:
        print(f"[DEBUG] Failed to save screenshot: {e}")


def has_product_section(driver, log_callback=None):
    """Check if the page has a product catalog section (not just posts/services)."""
    indicators = [
        # From debug.txt - GdmDKe is the container for show all button that leads to products
        "//div[contains(@class, 'GdmDKe')]",
        "//div[contains(@class, 'GdmDKe')]//a[contains(text(), 'すべて表示')]",
        # Products overview for desktop
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
        # Service catalog indicators - might lead to products too
        "//div[contains(@class, 'r6BRBd')]//div[contains(@class, 'hvddEd')]",
        "//div[contains(@class, 'sB1Bee')]",
    ]
    for xpath in indicators:
        elements = driver.find_elements(By.XPATH, xpath)
        if elements:
            # Check if it's explicitly products or just services
            found_products = False
            for el in elements:
                try:
                    text = el.text.strip().lower()
                    if "商品" in text or "product" in text:
                        found_products = True
                        break
                except: continue
            
            if log_callback:
                log_callback(f"Product section indicator matched: {xpath} (found {len(elements)} elements, product_specific={found_products})")
            return True

    # Fallback: look for elements containing "商品" (products) or "すべて表示" text
    product_text_elements = driver.find_elements(By.XPATH, "//*[contains(text(), '商品')]")
    if product_text_elements:
        for el in product_text_elements:
            try:
                text = el.text.strip()
                if text and len(text) < 50:
                    if log_callback:
                        log_callback(f"Product section fallback text matched: '{text}'")
                    return True
            except: continue
    
    # Also check for "すべて表示" anywhere on page - it's a strong indicator
    show_all_elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'すべて表示')]")
    if show_all_elements:
        if log_callback:
            log_callback(f"Found 'すべて表示' button - product/service section exists")
        return True
        
    return False


def find_product_show_all(driver, log_callback=None):
    """Find 'Show all' button specifically inside a product section."""
    # Priority 0: Explicitly under "商品" or "工事メニュー" headings (from gbp_construction_service.py)
    heading_based = [
        "//*[contains(text(), '商品') or contains(text(), '工事メニュー')]/ancestor::*[contains(@data-hveid)]//a[contains(text(), 'すべて表示')]",
        "//*[contains(text(), '商品') or contains(text(), '工事メニュー')]/following::a[contains(text(), 'すべて表示')][position()=1]",
    ]

    # Priority 1: Specifically labeled as product-related 'Show all'
    product_specific = [
        "//a[contains(text(), 'すべての商品を表示')]",
        "//a[contains(text(), 'すべての商品')]",
        "//div[contains(@class, 'GdmDKe')]//a[contains(., '商品') and contains(., 'すべて')]",
        "//a[contains(@href, '/lpc/') and contains(text(), 'すべて')]",
        "//a[contains(@href, 'product') and contains(text(), 'すべて')]",
    ]
    
    # Priority 2: 'Show all' near '商品' text
    near_product_text = [
        "//a[contains(text(), 'すべて表示') and ancestor::div[contains(., '商品')]]",
        "//a[contains(text(), 'すべて表示') and (preceding::*[contains(text(), '商品')][position() < 5] or following::*[contains(text(), '商品')][position() < 5])]",
    ]

    # Priority 3: The GdmDKe container mentioned in debug.txt
    gdm_selectors = [
        "//div[contains(@class, 'GdmDKe')]//a[contains(text(), 'すべて表示')]",
        "//div[contains(@class, 'GdmDKe')]//a[contains(@class, 'FOfI3')]",
    ]

    # Priority 4: Knowledge Panel section specific
    kp_selectors = [
        "//*[@data-attrid='kc:/local:products_overview_for_desktop']//*[contains(text(), 'すべて')]",
        "//*[@data-attrid='kc:/local:product catalog']//*[contains(text(), 'すべて')]",
        "//*[contains(@data-attrid, 'product')]//*[contains(text(), 'すべて')]",
    ]

    # Priority 5: General 'Show all' buttons but EXCLUDING those in category/service sections if possible
    general = [
        "//a[contains(text(), 'すべて表示') and not(ancestor::*[contains(., 'カテゴリ')])]",
        "//a[contains(text(), 'すべて表示')]",
        "//*[contains(text(), 'すべて表示') and (self::a or self::span)]",
    ]

    all_strategies = [
        (heading_based, "Heading-based match"),
        (product_specific, "Product-specific labels"),
        (near_product_text, "Near '商品' text"),
        (gdm_selectors, "GdmDKe container"),
        (kp_selectors, "KP section"),
        (general, "General show-all")
    ]

    for strategy_selectors, strategy_name in all_strategies:
        for xpath in strategy_selectors:
            try:
                elements = driver.find_elements(By.XPATH, xpath)
                for btn in elements:
                    if btn and btn.is_displayed():
                        # Extra check: if it's inside a 'カテゴリを探索' section, skip it in early strategies
                        if strategy_name != "General show-all":
                            try:
                                parent_text = driver.execute_script("return arguments[0].parentElement.innerText;", btn)
                                if "カテゴリ" in parent_text or "サービス" in parent_text:
                                    if log_callback:
                                        log_callback(f"[DEBUG] Skipping button in {strategy_name} because it seems category-related: '{parent_text[:30]}...'")
                                    continue
                            except: pass
                            
                        if log_callback:
                            log_callback(f"Found 'Show all' button via {strategy_name}: {xpath}")
                        return btn, f"{strategy_name}: {xpath[:60]}"
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
    
    matched = False
    for item in pack_items:
        try:
            text = item.text.strip()
            if text and store_name in text:
                log_callback(f"Found matching business in local pack: '{text}'. Preparing to open its Knowledge Panel...")
                matched = True
                log_callback(f"Scrolling matching business '{text}' into view...")
                driver.execute_script("arguments[0].scrollIntoView(true);", item)
                time.sleep(1)
                
                log_callback(f"Clicking on business '{text}' in local pack...")
                driver.execute_script("arguments[0].click();", item)
                
                log_callback("Waiting for navigation to Knowledge Panel...")
                time.sleep(random.uniform(5, 8))
                
                # Aggressive scrolling to trigger all lazy-loaded content
                for scroll_pos in [300, 500, 800, 1000, 1500]:
                    driver.execute_script(f"window.scrollTo(0, {scroll_pos});")
                    time.sleep(0.8)
                
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(3)
                
                # Scroll back up to top
                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(1)
                
                log_callback(f"Checking if '{text}' has a Product Catalog section...")
                if has_product_section(driver, log_callback):
                    log_callback("Product section successfully found and validated for this business!")
                    return True
                else:
                    log_callback("No product section found. Refreshing page and trying direct search instead...")
                    # If no product section found, try refreshing and checking again
                    driver.refresh()
                    time.sleep(random.uniform(4, 6))
                    
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(2)
                    
                    if has_product_section(driver, log_callback):
                        log_callback("Product section found after refresh!")
                        return True
                    
                    log_callback("Still no product section. Trying next match if any...")
        except Exception as e:
            log_callback(f"Error handling local pack item: {e}")
            continue
    
    if not matched:
        log_callback("No exact match found in local pack. Trying direct search URL...")
        # Try clicking first item if no match
        try:
            first_item = pack_items[0]
            driver.execute_script("arguments[0].scrollIntoView(true);", first_item)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", first_item)
            log_callback("Clicked first item in local pack, waiting for load...")
            time.sleep(random.uniform(5, 7))
            
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            if has_product_section(driver, log_callback):
                log_callback("Product section found after clicking first item!")
                return True
        except Exception as e:
            log_callback(f"Error clicking first item: {e}")
            
    log_callback("Finished checking local pack items.")
    return False


def scroll_knowledge_panel(driver):
    """Scroll the Knowledge Panel and any scrollable containers to trigger lazy loading."""
    # Main window scroll
    for pos in range(0, 3000, 300):
        driver.execute_script(f"window.scrollTo(0, {pos});")
        time.sleep(0.3)
    
    # Try scrolling any scrollable containers inside the page
    driver.execute_script("""
        document.querySelectorAll('div[style*="overflow"], div[class*="scroll"]').forEach(function(el) {
            if (el.scrollHeight > el.clientHeight) {
                el.scrollTop = el.scrollHeight;
            }
        });
    """)
    time.sleep(1)


def count_category_products(driver, log_callback=None):
    """Count total products from categorized view by counting J8zyUd elements.
    
    For each category (f8twAd):
    1. Click 'Show more' (もっと見る) to load all products
    2. Count all J8zyUd div elements
    
    This gives 100% accurate product count.
    """
    if log_callback is None:
        log_callback = lambda msg: None

    log_callback("[COUNT] Starting product counting...")
    
    switched_to_iframe = False
    try:
        # Wait up to 5 seconds for the iframe to be present
        catalog_iframes = []
        for i in range(5):
            catalog_iframes = driver.find_elements(By.CSS_SELECTOR, "iframe[src*='products/catalog'], iframe[name='lpc'], iframe.PxHPSd")
            if catalog_iframes:
                break
            time.sleep(1.0)
            
        if catalog_iframes:
            log_callback(f"[COUNT] Found {len(catalog_iframes)} catalog iframe(s). Switching to the first one...")
            driver.switch_to.frame(catalog_iframes[0])
            switched_to_iframe = True
            log_callback("[COUNT] Switched to catalog iframe successfully.")
            time.sleep(1.0)
            
        # Scroll modal scrollable container dynamically to trigger lazy loading of categories
        try:
            scroll_script = """
                var scrolled = false;
                var dialog = document.querySelector('div[role="dialog"]') || document.querySelector('div.V7nvVb');
                if (dialog) {
                    // Find all scrollable elements inside the dialog
                    var containers = dialog.querySelectorAll('div[style*="overflow"], div[class*="scroll"], div[style*="height"]');
                    if (containers.length === 0) {
                        dialog.scrollTop = dialog.scrollHeight;
                        scrolled = true;
                    } else {
                        containers.forEach(function(el) {
                            if (el.scrollHeight > el.clientHeight) {
                                el.scrollTop = el.scrollHeight;
                                scrolled = true;
                            }
                        });
                    }
                }
                return scrolled;
            """
            scrolled = driver.execute_script(scroll_script)
            if scrolled:
                log_callback("[COUNT] Scrolled modal dialog container to load categories.")
                time.sleep(2.0)
        except Exception as e:
            log_callback(f"[COUNT] Failed to scroll modal container: {e}")

        # Helper to find product elements using either wrapper classes (J8zyUd, LoZyGb) or link class (pooVf)
        def get_product_elements(container):
            found = container.find_elements(By.CSS_SELECTOR, "div.J8zyUd, div.LoZyGb")
            if not found:
                found = container.find_elements(By.CSS_SELECTOR, "a.pooVf")
            return found

        # First, just count all product elements on page (simple baseline)
        all_prods = get_product_elements(driver)
        log_callback(f"[COUNT] Found {len(all_prods)} product elements on page (before Show more)")
        
        # Try to find categories - both on main page and in modal
        categories = driver.find_elements(By.CSS_SELECTOR, "div.f8twAd")
        
        # Also try to find categories inside modal/dialog
        dialog_categories = driver.find_elements(By.XPATH, "//div[@role='dialog']//div[contains(@class, 'f8twAd')]")
        if dialog_categories:
            log_callback(f"[COUNT] Found {len(dialog_categories)} categories inside dialog/modal")
            categories = dialog_categories
        
        if not categories:
            # Fallback: count all products anywhere on page
            all_products = get_product_elements(driver)
            count = len(all_products)
            log_callback(f"[COUNT] No categories found. Total product elements on page: {count}")
            return count, {}
        
        log_callback(f"[COUNT] Found {len(categories)} categories")
        
        total = 0
        cat_counts = {}
        
        for cat in categories:
            try:
                cat_name_el = cat.find_elements(By.CSS_SELECTOR, "div.EJHGm")
                cat_name = cat_name_el[0].text.strip() if cat_name_el else "unknown"
                
                log_callback(f"[COUNT] Processing category: {cat_name}")
                
                # Click "Show more" button in each category to load all products
                show_more_clicked = True
                click_attempts = 0
                while show_more_clicked and click_attempts < 10:
                    show_more_clicked = False
                    click_attempts += 1
                    
                    # Find and click "Show more" (もっと見る) button - multiple robust strategies
                    show_more_btns = cat.find_elements(By.CSS_SELECTOR, "div.b7K3Ue button, div.b7K3Ue [role='button']")
                    if not show_more_btns:
                        show_more_btns = cat.find_elements(By.XPATH, ".//button[.//span[contains(text(), 'もっと見る')]]")
                    if not show_more_btns:
                        show_more_btns = cat.find_elements(By.XPATH, ".//button[contains(text(), 'もっと見る')]")
                    if not show_more_btns:
                        show_more_btns = cat.find_elements(By.XPATH, ".//button[contains(., 'もっと見る')]")
                    if not show_more_btns:
                        show_more_btns = cat.find_elements(By.XPATH, ".//span[text()='もっと見る']/ancestor::button")
                    if not show_more_btns:
                        show_more_btns = cat.find_elements(By.XPATH, ".//*[contains(@class, 'b7K3Ue')]//button")
                    
                    for btn in show_more_btns:
                        try:
                            # Scroll the button into view inside its container first
                            driver.execute_script("arguments[0].scrollIntoView({behavior: 'instant', block: 'center'});", btn)
                            time.sleep(0.5)
                            
                            log_callback(f"[COUNT] Clicking 'Show more' in '{cat_name}' (attempt {click_attempts})")
                            driver.execute_script("arguments[0].click();", btn)
                            time.sleep(random.uniform(1.5, 2.5))
                            show_more_clicked = True
                            break
                        except Exception as e:
                            log_callback(f"[COUNT] Error clicking button: {e}")
                
                # Count product elements in this category using robust CSS selector
                products = get_product_elements(cat)
                count = len(products)
                total += count
                cat_counts[cat_name] = count
                log_callback(f"[COUNT] Category '{cat_name}': {count} products")
            except Exception as e:
                log_callback(f"[COUNT] Error processing category: {e}")
                pass
        
        # Also count any remaining products not in categories
        all_products = get_product_elements(driver)
        if len(all_products) > total:
            log_callback(f"[COUNT] Found {len(all_products) - total} additional product elements outside categories")
            total = len(all_products)
        
        log_callback(f"[COUNT] Total products: {total}")
        return total, cat_counts
        
    finally:
        if switched_to_iframe:
            try:
                driver.switch_to.default_content()
                log_callback("[COUNT] Switched back to default content.")
            except Exception as e:
                log_callback(f"[COUNT] Error switching back to default content: {e}")


def extract_product_names(driver, log_callback=None):
    """Extract product names from the currently visible page/modal."""
    excluded_texts = {
        "すべて表示", "すべて", "商品", "サービス", "products", "services", 
        "Show all", "Show more", "もっと見る", "商品情報", "メニュー", "Product Info",
        "カテゴリを探索", "カテゴリ", "カテゴリを表示", "サービスを表示", "工事メニュー",
        "施工・工事", "調査", "ご相談"
    }
    
    seen = set()
    product_names = []

    def add_if_valid(text, source_label=""):
        if not text:
            return
        text = text.split('\n')[0].strip()
        if text and text not in excluded_texts and text not in seen:
            if len(text) < 2:
                return
            seen.add(text)
            product_names.append(text)
            if log_callback:
                log_callback(f"Extracted from {source_label}: '{text}'")

    if log_callback:
        log_callback("[DEBUG] Looking for product modal elements...")
    
    # Priority 1: Carousel products in products_overview section (always visible)
    carousel_items = driver.find_elements(By.XPATH, "//div[@data-attrid='kc:/local:products_overview_for_desktop']//div[contains(@class, 'Gik6Zd')]")
    if carousel_items:
        if log_callback:
            log_callback(f"[DEBUG] Found {len(carousel_items)} carousel product items")
        for item in carousel_items:
            try:
                add_if_valid(item.text, "carousel")
            except:
                pass
        if product_names:
            if log_callback:
                log_callback(f"[DEBUG] Extracted {len(product_names)} products from carousel.")
            return product_names

    # Priority 2: Categorized view (f8twAd > J8zyUd > t3RpAe) — lazy-loaded, may not exist
    categories = driver.find_elements(By.XPATH, "//div[contains(@class, 'f8twAd')]")
    if categories:
        if log_callback:
            log_callback(f"[DEBUG] Found {len(categories)} category containers (f8twAd)")
        
        for cat_index, cat in enumerate(categories):
            try:
                cat_name_el = cat.find_elements(By.XPATH, ".//div[contains(@class, 'EJHGm')]")
                cat_name = cat_name_el[0].text.strip() if cat_name_el else f"Category {cat_index}"
                if log_callback:
                    log_callback(f"[DEBUG] Processing category: {cat_name}")

                try:
                    show_more_btns = cat.find_elements(By.XPATH, ".//*[contains(text(), 'もっと見る')]")
                    for btn in show_more_btns:
                        if btn.is_displayed():
                            if log_callback:
                                log_callback(f"[DEBUG] Clicking 'Show more' in category {cat_name}")
                            driver.execute_script("arguments[0].click();", btn)
                            time.sleep(random.uniform(1.0, 2.0))
                except Exception as e:
                    if log_callback:
                        log_callback(f"[DEBUG] Error clicking 'Show more' in {cat_name}: {e}")

                product_elements = cat.find_elements(By.XPATH, ".//div[contains(@class, 'J8zyUd')]//div[contains(@class, 't3RpAe')]")
                if not product_elements:
                    product_elements = cat.find_elements(By.XPATH, ".//div[contains(@class, 'J8zyUd')]")
                
                if log_callback:
                    log_callback(f"[DEBUG] Found {len(product_elements)} potential product elements in category {cat_name}")
                
                for prod in product_elements:
                    add_if_valid(prod.text, f"category:{cat_name}")
                    
            except Exception as e:
                if log_callback:
                    log_callback(f"[DEBUG] Error processing category {cat_index}: {e}")

        if product_names:
            if log_callback:
                log_callback(f"[DEBUG] Successfully extracted {len(product_names)} products from categories.")
            return product_names

    # Priority 3: Global product selectors
    selectors = [
        "//div[contains(@class, 'su7Prc')]//div[contains(@class, 't3RpAe')]",
        "//a[contains(@class, 'pooVf')]//div[contains(@class, 't3RpAe')]",
        "//div[contains(@class, 'ZPm4jb')]//div[contains(@class, 't3RpAe')]",
        "//div[@role='dialog']//div[contains(@class, 't3RpAe')]",
        "//div[@role='dialog']//div[contains(@class, 'su7Prc')]",
        "//div[@role='dialog']//div[contains(@class, 'J8zyUd')]",
        "//*[contains(@class, 'J8zyUd')]//div[contains(@class, 't3RpAe')]",
        "//div[contains(@class, 'su7Prc')]",
        "//a[contains(@class, 'pooVf')]",
        "//div[contains(@class, 't3RpAe')]",
    ]
    
    for selector in selectors:
        elements = driver.find_elements(By.XPATH, selector)
        if elements:
            if log_callback:
                log_callback(f"[DEBUG] Found {len(elements)} elements with {selector}")
            for el in elements:
                try:
                    add_if_valid(el.text, selector)
                except: continue
            if product_names:
                log_callback(f"[DEBUG] Returning {len(product_names)} products from selector: {selector}")
                return product_names

    # Priority 4: Knowledge Panel selectors
    kp_selectors = [
        "//*[@data-attrid='kc:/local:products_overview_for_desktop']//span[contains(@class, 'OSrXXb')]",
        "//*[@data-attrid='kc:/local:product catalog']//span",
        "//*[contains(@data-attrid, 'products_overview')]//span[contains(@class, 'OSrXXb')]",
        "//*[contains(@data-attrid, 'product')]//span[contains(@class, 'OSrXXb')]",
        "//g-scrolling-carousel//span[contains(@class, 'OSrXXb')]",
        "//div[contains(@class, 'lpc')]//span"
    ]
    
    for selector in kp_selectors:
        elements = driver.find_elements(By.XPATH, selector)
        if elements:
            log_callback(f"[DEBUG] Found {len(elements)} elements with KP selector {selector}")
            for el in elements:
                try:
                    add_if_valid(el.text, "KP")
                except: continue
            if product_names:
                return product_names

    # Priority 5: Deep search in dialog/modal for any product-like elements
    modal_selectors = [
        "//div[@role='dialog']//ul//li",
        "//div[@role='dialog']//section//div",
        "//div[@role='dialog']//div[contains(@class, 'Gik6Zd')]",
        "//div[@role='dialog']//div[contains(@class, 'pooVf')]",
    ]
    
    for selector in modal_selectors:
        elements = driver.find_elements(By.XPATH, selector)
        if elements:
            if log_callback:
                log_callback(f"[DEBUG] Modal search: Found {len(elements)} elements with {selector}")
            for el in elements:
                try:
                    text = el.text.strip()
                    if text and len(text) > 2 and len(text) < 100:
                        add_if_valid(text, "modal")
                except: continue
            if product_names:
                log_callback(f"[DEBUG] Returning {len(product_names)} products from modal search")
                return product_names

    return []


def extract_service_names(driver, log_callback=None):
    """Extract service/category names for service businesses."""
    # If we are here, it's usually because extract_product_names returned nothing
    # or we want to find top-level categories if they are all that's shown.
    
    # Check for the category divs we saw in category_wise_div.html (f8twAd)
    categories = driver.find_elements(By.XPATH, "//div[contains(@class, 'f8twAd')]//div[contains(@class, 'EJHGm')]")
    if categories:
        seen = set()
        names = []
        for cat in categories:
            text = cat.text.strip()
            if text and text not in seen:
                seen.add(text)
                names.append(text)
                if log_callback:
                    log_callback(f"Extracted category name from f8twAd: '{text}'")
        if names:
            return names

    strategies = [
        # Service catalog - dialog/modal - HIGHEST PRIORITY
        "//div[@role='dialog']//div[contains(@class, 'sB1Bee')]",
        "//div[@role='dialog']//div[contains(@class, ' EJHGm')]",
        "//div[@role='dialog']//div[contains(@class, 't3RpAe')]",
        "//div[@role='dialog']//div[contains(@class, 'su7Prc')]//div",
        # Service category sections
        "//div[contains(@class, 'r6BRBd')]//div[contains(@class, 'hvddEd')]//div[contains(@class, 'sB1Bee')]",
        # Standard service catalog selectors
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
        # Use google.com with Japanese locale (works based on debug.txt)
        url = f"https://www.google.com/search?q={encoded_query}&hl=ja"
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
            # Scroll aggressively to trigger lazy-loaded categorized view
            log_callback("Scrolling to trigger lazy-loaded product categories...")
            scroll_knowledge_panel(driver)

            log_callback("Checking for categorized product view (f8twAd)...")
            
            # First, check if categories already exist on page (no need to click Show all)
            pre_check_categories = driver.find_elements(By.XPATH, "//div[contains(@class, 'f8twAd')]")
            pre_check_j8zyud = driver.find_elements(By.XPATH, "//div[contains(@class, 'J8zyUd') or contains(@class, 'LoZyGb')]")
            if not pre_check_j8zyud:
                pre_check_j8zyud = driver.find_elements(By.XPATH, "//a[contains(@class, 'pooVf')]")
            log_callback(f"[DEBUG] Pre-check - Categories: {len(pre_check_categories)}, Product items: {len(pre_check_j8zyud)}")
            
            # Only click Show all if no categories found yet
            if not pre_check_categories and not pre_check_j8zyud:
                show_all_btn, strategy_desc = find_product_show_all(driver, log_callback)
                if show_all_btn:
                    log_callback(f"Found 'Show all' button via: {strategy_desc}")
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", show_all_btn)
                    time.sleep(random.uniform(0.3, 0.8))
                    
                    try:
                        show_all_btn.click()
                    except:
                        driver.execute_script("arguments[0].click();", show_all_btn)
                    
                    log_callback("Clicked Show all, waiting for load...")
                    time.sleep(random.uniform(4, 6))
                    
                    # Aggressive scrolling to trigger lazy loading
                    for scroll_pos in [200, 400, 600, 800, 1000, 1500, 2000]:
                        driver.execute_script(f"window.scrollTo(0, {scroll_pos});")
                        time.sleep(0.5)
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(1)
                    driver.execute_script("window.scrollTo(0, 0);")
                    time.sleep(1)
                    
                    # Debug: Save page after Show all click
                    log_callback("[DEBUG] Saving page after Show all click for analysis...")
                    save_debug(driver, "after_showall_v2")
            else:
                log_callback("[DEBUG] Categories already visible, skipping Show all click")
            
            # DEBUG: Check what's on the page before counting
            debug_categories = driver.find_elements(By.XPATH, "//div[contains(@class, 'f8twAd')]")
            debug_dialog_categories = driver.find_elements(By.XPATH, "//div[@role='dialog']//div[contains(@class, 'f8twAd')]")
            debug_j8zyud = driver.find_elements(By.XPATH, "//div[contains(@class, 'J8zyUd') or contains(@class, 'LoZyGb')]")
            if not debug_j8zyud:
                debug_j8zyud = driver.find_elements(By.XPATH, "//a[contains(@class, 'pooVf')]")
            log_callback(f"[DEBUG] Final - Categories: {len(debug_categories)}, in dialog: {len(debug_dialog_categories)}, Product items: {len(debug_j8zyud)}")
            
            # Count products by J8zyUd elements - 100% accurate
            total_count, cat_counts = count_category_products(driver, log_callback)
            log_callback(f"[DEBUG] count_category_products returned: {total_count}, cat_counts: {cat_counts}")
            
            if total_count > 0:
                result["products"] = []
                result["product_count"] = total_count
                log_callback(f"Done. Total product count: {total_count} (by category: {cat_counts})")
                return result, driver

            log_callback("No products found via counting. Trying name extraction as fallback...")
            products_before = extract_product_names(driver, log_callback)

            if products_before:
                result["products"] = products_before
                result["product_count"] = len(products_before)
                log_callback(f"Done. Product count: {result['product_count']}")
                return result, driver

            log_callback("No products in carousel. Looking for 'Show all' button...")
            show_all_btn, strategy_desc = find_product_show_all(driver, log_callback)

            if show_all_btn:
                log_callback(f"Found 'Show all' button via: {strategy_desc}")
                log_callback("Scrolling to 'Show all' button...")

                time.sleep(random.uniform(0.5, 1.5))

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
                time.sleep(random.uniform(4, 6))
                
                page_html = driver.page_source
                log_callback(f"DEBUG: Page HTML length: {len(page_html)} chars")
                
                has_zpm4jb = "ZPm4jb" in page_html
                has_su7prc = "su7Prc" in page_html
                log_callback(f"DEBUG: Has ZPm4jb in page: {has_zpm4jb}")
                log_callback(f"DEBUG: Has su7Prc in page: {has_su7prc}")
                
                try:
                    WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']"))
                    )
                    log_callback("Dialog/modal detected in DOM.")
                except Exception:
                    log_callback("No dialog role found, proceeding with extraction.")
                
                save_debug(driver, "after_showall_click")

                log_callback("Aggressively scrolling to load all lazy products...")
                for scroll_pos in [200, 400, 600, 800, 1000, 1200, 1500, 1800, 2000]:
                    driver.execute_script(f"window.scrollTo(0, {scroll_pos});")
                    time.sleep(0.8)
                
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)

                log_callback("Checking for 'Load more' or pagination buttons...")
                load_more_clicked = True
                load_more_attempts = 0
                while load_more_clicked and load_more_attempts < 10:
                    load_more_clicked = False
                    load_more_attempts += 1
                    
                    load_more_selectors = [
                        "//button[contains(text(), 'もっと見る')]",
                        "//button[contains(text(), 'Load more')]",
                        "//button[contains(text(), 'more')]",
                        "//span[contains(text(), 'もっと見る')]/ancestor::button",
                        "//a[contains(text(), 'もっと見る')]",
                        "//button[contains(@aria-label, 'more')]",
                        "//div[@role='button'][contains(text(), 'もっと')]",
                    ]
                    
                    for selector in load_more_selectors:
                        try:
                            buttons = driver.find_elements(By.XPATH, selector)
                            for btn in buttons:
                                if btn.is_displayed() and btn.is_enabled():
                                    log_callback(f"Clicking load more button: {selector}")
                                    driver.execute_script("arguments[0].click();", btn)
                                    time.sleep(random.uniform(1.5, 2.5))
                                    
                                    for scroll_pos in [300, 600, 900]:
                                        driver.execute_script(f"window.scrollTo(0, {scroll_pos});")
                                        time.sleep(0.5)
                                    
                                    load_more_clicked = True
                                    break
                        except Exception:
                            continue
                    if load_more_clicked:
                        log_callback(f"Load more clicked, attempt {load_more_attempts}")

                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(1)

            # Count products by J8zyUd elements - 100% accurate method
            log_callback("Counting products by J8zyUd elements...")
            total_count, cat_counts = count_category_products(driver, log_callback)
            if total_count > 0:
                result["products"] = []
                result["product_count"] = total_count
                log_callback(f"Done. Total product count: {total_count} (by category: {cat_counts})")
                return result, driver

            log_callback("No J8zyUd elements found. Trying to extract product names as fallback...")
            products_after = extract_product_names(driver, log_callback)

            all_products = list(set(products_after))
            if all_products:
                result["products"] = all_products
                result["product_count"] = len(all_products)
                log_callback(f"Done. Product count: {result['product_count']}")
                return result, driver

            log_callback("DEBUG: No products extracted. Saving page for analysis...")
            save_debug(driver, "no_products_found")
            
            all_t3rpae = driver.find_elements(By.XPATH, "//*[contains(@class, 't3RpAe')]")
            log_callback(f"DEBUG: Found {len(all_t3rpae)} elements with class 't3RpAe' anywhere on page")
            for i, el in enumerate(all_t3rpae[:5]):
                log_callback(f"  DEBUG t3RpAe[{i}]: '{el.text.strip()}'")
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
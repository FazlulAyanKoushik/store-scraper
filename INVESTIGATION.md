# Investigation: Can Google Store Product Scraping Be Done?

## Short Answer

**Partially yes, but with severe limitations.** Scraping products from Google search results by store name is possible only under very specific conditions — and the current approach has fundamental problems that make it unreliable.

---

## Root Cause: The Store Must Have a Product Section

The single biggest issue: **Google only shows a "Products" section for retail/e-commerce businesses that have added products to their Google Business Profile.** Service businesses (like `美匠`, a painting contractor) do NOT get a product catalog.

### From debug.txt — What "美匠" Actually Shows:

| Section | Content | Type |
|---------|---------|------|
| `カテゴリを探索` (Explore categories) | 施工・工事, 調査, ご相談 | **Service categories** |
| Business Posts | Dated updates with photos | **Social-media posts** |
| Knowledge Panel | Business info, description, hours | **Static info** |

There is **zero product inventory** on this page. The "すべて表示" (Show all) button opens a modal for posts, not products.

### When DO Products Appear?

Only when the business:
1. Has a **retail category** (e.g., "Clothing store", "Electronics store", "Grocery store")
2. Has **manually added products** via Google Business Profile dashboard, OR
3. Has **integrated Google Merchant Center** with an e-commerce platform (Shopify, WooCommerce, etc.)

---

## Evidence from Google's Own Documentation

| Source | Finding |
|--------|---------|
| Google Support (2025) | "Products" feature is only for **local stores that sell physical goods** |
| Google Support (2025) | "This feature isn't available for all Business Profiles" — explicitly excludes service businesses |
| Google Ads Liaison (2023) | "Products will remain available in GBP" — but only for merchants, not service businesses |
| Flento (2026) | "If you see 'Menu' instead of 'Products', your business category may require a different content format" |

---

## The Product Section Has Been Unstable

Even for eligible businesses, the "Products" section on Google has a history of breakage:

- **2022**: Google unpublished manually-added products, redirected to Merchant Center
- **2023**: Google clarified Products "will remain available" — but only for retail
- **2024**: Multiple reports of Products disappearing from desktop side panel (localSEOforum thread)
- **2024**: `shopping_results` inconsistent on desktop — only 68% of queries returned products (SerpAPI GitHub issue)
- **2025**: Asynchronous JavaScript rendering became **mandatory** for SERP results — plain HTTP scraping died
- **2025**: Legacy product detail page URLs deprecated, replaced by async "Immersive Product" surface
- **2025**: Q&A API shut down — Google moving away from publicly-scrapable business data
- **2026**: Products feature still exists but display is controlled by Google's algorithms, not guaranteed

---

## Anti-Scraping Barriers (Why Selenium Fails)

Multiple layers of anti-bot protection are now active:

### 1. reCAPTCHA / reCAPTCHA v2
Google serves CAPTCHAs aggressively when it detects automation. The scraper already handles this with 2Captcha, but this adds latency, cost, and is not always successful.

### 2. SearchGuardLite
The debug.html shows Google's SearchGuardLite (lines 25-27), which:
- Intercepts all XHR requests
- Checks for `X-Sg-Cs` response headers
- Reloads page or shows "Sorry" page if suspicious activity detected

### 3. Dynamic DOM / Obfuscated Class Names
Google uses auto-generated, randomized class names (e.g., `BFOCWc`, `OSrXXb`, `Gik6Zd`). These change frequently. The scraper's XPath selectors are brittle and require constant updates.

### 4. JavaScript-Rendered Content
As of January 2025, JavaScript execution is **mandatory** for Google SERP results. Content is loaded via:
- Async XHR after the initial page load
- Google Web Components (`g-scrolling-carousel`, `c-wiz`, `g-left-button`)
- Protobuf-encoded data in `<c-data>` tags

### 5. IP Rate Limiting / Proxy Requirements
Google tracks and rate-limits IPs. Even with Bright Data residential proxies, the scraper frequently hits reCAPTCHA walls (as shown in the code's retry logic).

### 6. Location-Based Content Differences
The scraper uses `hl=ja&gl=jp` for Japanese locale. Content varies by:
- IP geolocation (not just URL parameters)
- Login state (logged-in users see different content)
- Device type (mobile vs desktop shows different HTML structure)

---

## What the Scraper Actually Extracts

From the existing code analysis:

| Attempt | What It Finds | Why It Fails |
|---------|---------------|-------------|
| `data-attrid='kc:/local:products_overview_for_desktop'` | **Never found** for service businesses | Attribute only exists for retail GBP products |
| `//*[text()='すべて表示']` | **Found** but linked to posts/services | Clicking opens a post modal, NOT products |
| `//*[contains(@class, 'OSrXXb')]` | **Found** but are post titles, not products | Class is reused across different sections |
| `//div[contains(@class, 'sB1Bee')]` | **Found** — service category names | Extracts "施工・工事" etc., not products |
| `g-scrolling-carousel` | **Found** but contains posts/media | Not product data |

The scraper's `extract_product_names()` returns post text or service category names and mislabels them as "products."

---

## Alternative Approaches That Might Work

### Option A: Google Business Profile API (Official)
- **What**: Use Google's official Business Profile APIs to read product data
- **Requires**: GBP API access, OAuth, business verification
- **Limitation**: Only works for businesses YOU manage. Cannot read ANY store's products.
- **Relevance**: Not useful for a public-facing scraper — only for business owners.

### Option B: Google Shopping Results API (SERP API services)
- **What**: Services like SerpAPI, DataForSEO, ScrapingBee provide structured Google Shopping data
- **Cost**: Paid ($0.003–$0.05 per request)
- **Limitation**: Returns shopping ads and general product listings, NOT a specific store's catalog from their GBP
- **Relevance**: Works for keyword-based product search, not "show me products of store X"

### Option C: Google Merchant Center API
- **What**: Returns product feed data for businesses that use Merchant Center
- **Requires**: Merchant Center account access (only the business owner)
- **Limitation**: Cannot access other stores' data

### Option D: Manual Product Upload by Store Owners
- **What**: Ask store owners to manually upload product data
- **Relevance**: The only reliable way to get per-store product lists

---

## Summary: Is It Possible?

| Scenario | Possible? | Notes |
|----------|-----------|-------|
| Scrape products for a retail store with GBP products | **Rarely** | Works ~30% of the time; Google blocks aggressively; DOM changes break selectors |
| Scrape service categories for a service business | **Yes** | The "カテゴリを探索" section is reliably present for service businesses |
| Scrape posts (not products) for any business | **Yes** | Google Business Profile posts are reliably shown |
| Determine product COUNT from Google search page | **NO** | No reliable method exists. Product counts are not exposed in the HTML at all. |

### Final Verdict

**The project "Google Store Product Scraper" as designed cannot work reliably** because:

1. **Most businesses are service businesses** — they have no product catalog on Google
2. **Even for retail businesses**, the product section is inconsistently displayed, frequently restructured, and heavily protected by anti-scraping measures
3. **Google does not expose product counts** in search result HTML — the count can only be inferred by scraping individual product names
4. **The scraper currently misidentifies posts/services as products**, giving incorrect results

The only viable path forward would be to:
- Use **Google Business Profile API** with OAuth (requires business owner authorization)
- **Restrict to retail businesses only** and accept high failure rates
- **Use paid SERP APIs** (SerpAPI, DataForSEO) instead of Selenium to bypass anti-bot measures
- **Shift focus to service categories** (which ARE reliably available) instead of products

"""! @file fp_utils.py
@brief Shared utility helpers for XML, text extraction, HTTP auth, and page loading.

The functions in this module are intentionally stateless and reusable from parser
and writer modules.
"""

import os
import re
import unicodedata
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from fp_config import BASE_URL, LOGIN_PAGE, LOGIN_POST, HEADERS, GPX_NS


def gpx_tag(name):
    """! @brief Build a GPX namespaced tag for ElementTree operations.
    @param name Local (non-namespaced) tag name.
    @return Fully-qualified namespaced tag string.
    """
    return f"{{{GPX_NS}}}{name}"


def add_text_element(parent, name, value, namespace=GPX_NS):
    """! @brief Append a text child element only when value is non-empty.
    @param parent Parent XML element.
    @param name Child tag name.
    @param value Value assigned to child text; skipped when empty.
    @param namespace Namespace URI or falsy value for plain tag.
    @return Newly created child element or None when skipped.
    """
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None

    tag = gpx_tag(name) if namespace else name
    child = ET.SubElement(parent, tag)
    child.text = value
    return child


def format_tree(tree):
    """! @brief Apply 2-space indentation to an ElementTree.
    @param tree XML tree to format.
    @return Same input tree after in-place indentation.
    """
    ET.indent(tree, space="  ", level=0)
    return tree


def clean_text(t):
    """! @brief Normalize contiguous whitespace to single spaces.
    @param t Input text value (nullable).
    @return Trimmed string with compacted whitespace.
    """
    return re.sub(r"\s+", " ", (t or "")).strip()


def extract_private_links(text):
    """! @brief Extract Park4Night and Wikipedia URLs from private text notes.
    @param text Raw note text that may include URLs.
    @return Tuple (cleaned_text, park4night_url, wikipedia_urls).
    """
    if not text:
        return "", "", []

    url_pattern = re.compile(r"https?://[^\s]+", flags=re.IGNORECASE)
    park4night_url = ""
    wikipedia_urls = []

    def _replace(match):
        nonlocal park4night_url
        url = match.group(0)
        lowered = url.lower()

        if "park4night" in lowered:
            if not park4night_url:
                park4night_url = url
            return ""

        if "wikipedia.org" in lowered:
            if url not in wikipedia_urls:
                wikipedia_urls.append(url)
            return ""

        return url

    cleaned = url_pattern.sub(_replace, text)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, park4night_url, wikipedia_urls


def extract_expandable_text(node):
    """! @brief Extract normalized text from footprint expandable HTML blocks.
    @param node BeautifulSoup node to transform.
    @return Plain-text rendering with line break semantics preserved.
    """
    if not node:
        return ""

    parsed = BeautifulSoup(str(node), "html.parser")
    root = parsed.find()
    if not root:
        return ""

    def strip_scheme(url):
        """! @brief Remove URL scheme and protocol-relative prefix.
        @param url Input URL.
        @return URL body without leading scheme.
        """
        if not url:
            return ""
        cleaned = url.strip()
        cleaned = re.sub(r"^//", "", cleaned)
        return re.sub(r"^https?://", "", cleaned, flags=re.IGNORECASE)

    def to_https_url(url):
        """! @brief Normalize any URL-ish text to explicit https URL.
        @param url Input URL-like value.
        @return Normalized https URL or empty string.
        """
        body = strip_scheme(url)
        if not body:
            return ""
        return "https://" + body

    for dots in root.select(".dots"):
        prev_a = dots.find_previous("a")
        next_a = dots.find_next("a")
        if not prev_a or not next_a:
            continue
        prev_href = prev_a.get("href", "")
        next_href = next_a.get("href", "")
        prev_body = strip_scheme(prev_href)
        next_body = strip_scheme(next_href)
        if not (prev_body and next_body):
            continue
        merged_body = prev_body + next_body
        merged_url = "https://" + merged_body
        prev_a["href"] = merged_url
        prev_a.string = merged_url
        next_a.decompose()

    for a in root.select("a[href]"):
        href = a.get("href", "")
        if re.match(r"^(https?://|//)", href.strip(), flags=re.IGNORECASE):
            normalized = to_https_url(href)
            if normalized:
                a.string = normalized

    for tag in root.select(".readMore, .dots, i.icon-font"):
        tag.decompose()

    for br in root.find_all("br"):
        br.replace_with("\n")
    for dbl in root.select(".double-break"):
        dbl.replace_with("\n\n")

    text = root.get_text(separator="", strip=False)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_photo_url(img_url):
    """! @brief Promote thumbnail suffixes to large-image suffixes.
    @param img_url Original FindPenguins image URL.
    @return URL rewritten to use `_l` variant when available.
    """
    parsed = urlparse(img_url)
    dirname, filename = os.path.split(parsed.path)
    new_filename = re.sub(r"(_m_s|_t_s)(\.[A-Za-z0-9]+)$", r"_l\\2", filename)
    new_path = os.path.join(dirname, new_filename)
    return parsed._replace(path=new_path).geturl()


def download_image(img_url, dest_folder, prefix="img"):
    """! @brief Download one image and save it to local storage.
    @param img_url Remote image URL.
    @param dest_folder Destination directory path.
    @param prefix Filename prefix prepended to saved image name.
    @return Absolute/relative path of the saved local file.
    @exception requests.RequestException Raised on HTTP failures.
    """

    os.makedirs(dest_folder, exist_ok=True)
    if img_url.startswith("//"):
        img_url = "https:" + img_url
    elif img_url.startswith("/"):
        img_url = urljoin(BASE_URL, img_url)
    img_url = normalize_photo_url(img_url)

    parsed = urlparse(img_url)
    filename = os.path.basename(parsed.path) or "image.jpg"
    local_name = f"{prefix}_{filename}"
    local_path = os.path.join(dest_folder, local_name)

    resp = requests.get(img_url, headers=HEADERS, stream=True, timeout=20)
    resp.raise_for_status()
    with open(local_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)
    return local_path


def requests_cookies_to_playwright(session):
    """! @brief Convert requests cookies into Playwright cookie objects.
    @param session Authenticated requests session.
    @return List of cookie dictionaries accepted by Playwright context.
    """
    cookies = []
    for cookie in session.cookies:
        cookie_data = {
            "name": cookie.name,
            "value": cookie.value,
            "path": cookie.path or "/",
        }
        domain = (cookie.domain or "").lstrip(".")
        if domain:
            cookie_data["domain"] = domain
        else:
            cookie_data["url"] = BASE_URL
        if cookie.expires:
            cookie_data["expires"] = cookie.expires
        cookies.append(cookie_data)
    return cookies


def create_browser_page(session):
    """! @brief Create a headless Playwright page seeded with session cookies.
    @param session Authenticated requests session.
    @return Tuple (playwright, browser, page).
    """
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(user_agent=HEADERS["User-Agent"])
    cookies = requests_cookies_to_playwright(session)
    if cookies:
        context.add_cookies(cookies)
    page = context.new_page()
    return playwright, browser, page


def click_load_more_until_done(page):
    """! @brief Expand trip footprint list by clicking load-more until exhausted.
    @param page Active Playwright page instance.
    @return None
    """
    footprint_selector = "ul.FootprintList li.footprint"
    load_more_selector = "#footprintListLoadMore"

    while True:
        load_more = page.locator(load_more_selector)
        if load_more.count() == 0:
            break

        button = load_more.first
        try:
            if not button.is_visible():
                break
        except Exception:
            break

        before_count = page.locator(footprint_selector).count()
        button.click()
        try:
            page.wait_for_function(
                """(beforeCount) => {
                    const current = document.querySelectorAll('ul.FootprintList li.footprint').length;
                    const loadMore = document.querySelector('#footprintListLoadMore');
                    return current > beforeCount || !loadMore || loadMore.offsetParent === null;
                }""",
                arg=before_count,
                timeout=15000,
            )
        except PlaywrightTimeoutError:
            break


def login(username, password):
    """! @brief Authenticate to FindPenguins using form-based login.
    @param username Login username/email.
    @param password Account password.
    @return Authenticated requests.Session carrying cookies.
    """

    print("Logging ...")

    session = requests.Session()
    resp = session.get(LOGIN_PAGE)
    soup = BeautifulSoup(resp.text, "html.parser")

    csrf = soup.find("input", {"name": "_csrf_token"})["value"]

    payload = {
        "_username": username,
        "_password": password,
        "_csrf_token": csrf,
        "_remember_me": "on",
        "exec-login": "",
    }

    resp = session.post(LOGIN_POST, data=payload)

    if resp.ok and "logout" in resp.text.lower():
        print("  Logged in!")

    return session


def load_page(page, page_url, outputdir, save_html=True):
    """! @brief Navigate to page URL, resolve dynamic content, and parse HTML.
    @param page Active Playwright page.
    @param page_url Target URL to open.
    @param outputdir Output directory used for optional HTML snapshots.
    @param save_html When true, save prettified HTML to disk.
    @return BeautifulSoup instance for the loaded page content.
    """

    parts = urlparse(page_url)
    _dirname, filename = os.path.split(parts.path)

    print(f"  - Getting page [{page_url}] ...")
    page.goto(page_url, wait_until="domcontentloaded", timeout=30000)

    if "/trip/" in parts.path:
        click_load_more_until_done(page)

    soup = BeautifulSoup(page.content(), "html.parser")

    file_stem = filename
    if "/trip/" in parts.path:
        title_el = soup.select_one("h1.headline")
        title = " ".join(title_el.get_text().split()) if title_el else ""
        if title:
            ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
            slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_title).strip("-").lower()
            if slug:
                file_stem = slug

    if save_html:
        page_html = os.path.join(outputdir, file_stem + ".html")
        with open(page_html, "w", encoding="utf-8") as f:
            f.write(soup.prettify())

    return soup

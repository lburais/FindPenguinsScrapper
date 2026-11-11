"""! @file fp_utils.py
@brief Shared utility helpers for XML, text extraction, HTTP auth, and page loading.

The functions in this module are intentionally stateless and reusable from parser
and writer modules.
"""

import os
import re
import hashlib
import unicodedata
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from PIL import Image
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


def strip_leading_flag(text):
    """Remove a leading Unicode country or subdivision flag from text."""
    return re.sub(
        r"^\s*(?:[\U0001f1e6-\U0001f1ff]{2}|\U0001f3f4[\U000e0020-\U000e007e]+\U000e007f)\s*",
        "", str(text or ""),
    ).strip()


def extract_private_references(text):
    """! @brief Extract URL references from private text notes.
    @param text Raw note text that may include URLs.
    @return Tuple (cleaned_text, list of (search_text, url) references).
    """
    if not text:
        return "", []

    references = []
    text_lines = []
    for line in text.splitlines():
        line_text = line.strip()
        search_text = ""
        url = line_text
        if line_text.startswith("[") and "]" in line_text:
            search_end = line_text.index("]")
            search_text = line_text[1:search_end].strip()
            url = line_text[search_end + 1:].strip()

        try:
            parsed_url = urlparse(url)
            valid_url = (
                parsed_url.scheme.lower() in ("http", "https")
                and bool(parsed_url.hostname)
                and not any(char.isspace() for char in url)
            )
            parsed_url.port
        except ValueError:
            valid_url = False

        if valid_url:
            reference = search_text, url
            if reference not in references:
                references.append(reference)
        else:
            text_lines.append(line)

    cleaned = "\n".join(text_lines)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, references


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
    new_filename = re.sub(r"(_m_s|_t_s)(\.[A-Za-z0-9]+)$", r"_l\2", filename)
    new_path = os.path.join(dirname, new_filename)
    return parsed._replace(path=new_path).geturl()


def to_webp(path):
    """! @brief Convert an image to lossless WebP next to the source and remove the source.
    @param path Source image path.
    @return Path of the WebP file (unchanged when already WebP).
    """
    if path.lower().endswith(".webp"):
        return path
    webp_path = os.path.splitext(path)[0] + ".webp"
    with Image.open(path) as image:
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "transparency" in image.info or image.mode in ("LA", "PA") else "RGB")
        image.save(webp_path, "WEBP", lossless=True, quality=100, method=4, exact=True)
    os.remove(path)
    return webp_path


def variant_path(path, suffix):
    """! @brief Return the path of a size variant, e.g. `a.webp` -> `a_large.webp`."""
    root, ext = os.path.splitext(path)
    return f"{root}_{suffix}{ext}"


def make_variant(path, suffix, max_size):
    """! @brief Create a lossless WebP copy of an image whose longest side is at most `max_size`.
    The original is kept and never upscaled; an existing variant of the right size is reused.
    @param path Source WebP image path.
    @param suffix Variant suffix (e.g. "small", "medium", "large").
    @param max_size Maximum width/height in pixels.
    @return Path of the variant file.
    """
    target = variant_path(path, suffix)
    with Image.open(path) as image:
        expected = image.size
        if max(expected) > max_size:
            ratio = max_size / max(expected)
            expected = (max(1, round(expected[0] * ratio)), max(1, round(expected[1] * ratio)))
        if os.path.isfile(target):
            with Image.open(target) as existing:
                if existing.size == expected:
                    return target
        resized = image.copy()
        if resized.size != expected:
            resized = resized.resize(expected, Image.LANCZOS)
        resized.save(target, "WEBP", lossless=True, quality=100, method=4, exact=True)
    return target


def shrink_image(path, max_size):
    """! @brief Downscale a WebP image in place (lossless) so its longest side is at most `max_size`.
    Images already small enough are left untouched.
    @param path WebP image path.
    @param max_size Maximum width/height in pixels.
    @return The same path.
    """
    with Image.open(path) as image:
        if max(image.size) <= max_size:
            return path
        ratio = max_size / max(image.size)
        resized = image.resize((max(1, round(image.width * ratio)), max(1, round(image.height * ratio))), Image.LANCZOS)
    resized.save(path, "WEBP", lossless=True, quality=100, method=4, exact=True)
    return path


def download_image(img_url, dest_folder, prefix="img", filename=None, refresh=False):
    """! @brief Download one image and save it to local storage.
    @param img_url Remote image URL.
    @param dest_folder Destination directory path.
    @param prefix Filename prefix prepended to saved image name.
    @param filename Optional filename stem to use instead of the URL-derived name.
    @param refresh Whether to download again when the destination already exists.
    @return Path of the saved lossless WebP file.
    @exception requests.RequestException Raised on HTTP failures.
    """

    os.makedirs(dest_folder, exist_ok=True)
    if img_url.startswith("//"):
        img_url = "https:" + img_url
    elif img_url.startswith("/"):
        img_url = urljoin(BASE_URL, img_url)
    img_url = normalize_photo_url(img_url)

    parsed = urlparse(img_url)
    source_name = os.path.basename(parsed.path) or "image.jpg"
    local_name = (
        f"{filename}{os.path.splitext(source_name)[1] or '.jpg'}"
        if filename else f"{prefix}_{source_name}"
    )
    local_path = os.path.join(dest_folder, local_name)
    webp_path = os.path.splitext(local_path)[0] + ".webp"
    if not refresh and os.path.exists(webp_path):
        return webp_path

    resp = requests.get(img_url, headers=HEADERS, stream=True, timeout=20)
    resp.raise_for_status()
    with open(local_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)
    return to_webp(local_path)


def download_video(video_url, dest_folder, prefix="vid"):
    """! @brief Download one video and save it to local storage (skipped when already present).
    @param video_url Remote video URL.
    @param dest_folder Destination directory path.
    @param prefix Filename prefix prepended to saved video name.
    @return Local path of the saved file.
    @exception requests.RequestException Raised on HTTP failures.
    """

    os.makedirs(dest_folder, exist_ok=True)
    if video_url.startswith("//"):
        video_url = "https:" + video_url
    elif video_url.startswith("/"):
        video_url = urljoin(BASE_URL, video_url)

    filename = os.path.basename(urlparse(video_url).path) or "video.mp4"
    local_path = os.path.join(dest_folder, f"{prefix}_{filename}")
    if os.path.exists(local_path):
        return local_path

    # Download to a temp name so an interrupted transfer is never mistaken for a finished file.
    partial_path = local_path + ".part"
    with requests.get(video_url, headers=HEADERS, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(partial_path, "wb") as f:
            for chunk in resp.iter_content(1024 * 256):
                if chunk:
                    f.write(chunk)
    os.replace(partial_path, local_path)
    return local_path


def download_file(file_url, dest_folder, prefix="file", default_ext=""):
    """! @brief Download one attachment (GPX, PDF...) and save it to local storage (skipped when already present).
    @param file_url Remote file URL.
    @param dest_folder Destination directory path.
    @param prefix Filename prefix prepended to saved file name.
    @param default_ext Extension appended when the URL file name has none (e.g. ".pdf").
    @return Local path of the saved file.
    @exception requests.RequestException Raised on HTTP failures.
    """

    os.makedirs(dest_folder, exist_ok=True)
    if file_url.startswith("//"):
        file_url = "https:" + file_url
    elif file_url.startswith("/"):
        file_url = urljoin(BASE_URL, file_url)

    filename = os.path.basename(urlparse(file_url).path) or f"file{default_ext}"
    if default_ext and not os.path.splitext(filename)[1]:
        filename += default_ext
    local_path = os.path.join(dest_folder, f"{prefix}_{filename}")
    if os.path.exists(local_path):
        return local_path

    partial_path = local_path + ".part"
    with requests.get(file_url, headers=HEADERS, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(partial_path, "wb") as f:
            for chunk in resp.iter_content(1024 * 64):
                if chunk:
                    f.write(chunk)
    os.replace(partial_path, local_path)
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


class SnapshotError(RuntimeError):
    """A required saved HTML snapshot cannot be used."""


def snapshot_path(page_url, outputdir, suffix="html"):
    """Return a stable, URL-specific snapshot path."""
    digest = hashlib.sha256(page_url.encode("utf-8")).hexdigest()
    return os.path.join(outputdir, f"page-{digest}.{suffix}")


def _snapshot_slug(text):
    """Return `text` as a lowercase ASCII, hyphen-separated slug (used to find legacy snapshots)."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-").lower()


def load_page(page, page_url, outputdir, skip=False, title="", footprint_id=""):
    """! @brief Navigate to page URL, resolve dynamic content, and parse HTML.
    @param page Active Playwright page.
    @param page_url Target URL to open.
    @param outputdir Output directory used for HTML snapshots.
    @param skip When true, read a saved snapshot instead of navigating.
    @param title Optional title for locating snapshots saved by older versions.
    @param footprint_id Optional footprint identifier for locating older snapshots.
    @return BeautifulSoup instance for the loaded page content.
    """

    parts = urlparse(page_url)
    _dirname, filename = os.path.split(parts.path)

    if skip:
        path = snapshot_path(page_url, outputdir)
        if not os.path.isfile(path):
            legacy_names = [filename]
            if title:
                legacy_names.insert(0, _snapshot_slug(title))
            candidates = [os.path.join(outputdir, name + ".html") for name in legacy_names if name]
            if footprint_id and os.path.isdir(outputdir):
                matches = []
                for name in os.listdir(outputdir):
                    if not name.endswith(".html") or name == "insights.html":
                        continue
                    candidate = os.path.join(outputdir, name)
                    with open(candidate, encoding="utf-8") as handle:
                        legacy_soup = BeautifulSoup(handle, "html.parser")
                    if legacy_soup.select_one(f"li.footprint[data-id='{footprint_id}'] h1.headline"):
                        matches.append(candidate)
                if len(matches) > 1:
                    raise SnapshotError(f"Multiple saved snapshots match footprint {footprint_id}: {matches}")
                candidates = matches
            path = next((candidate for candidate in candidates if os.path.isfile(candidate)), "")
        if not path:
            raise SnapshotError(f"No saved HTML snapshot for {page_url} in {outputdir}; scrape the page first")
        print(f"  - Reading saved page [{path}] ...")
        with open(path, encoding="utf-8") as handle:
            return BeautifulSoup(handle, "html.parser")

    print(f"  - Getting page [{page_url}] ...")
    page.goto(page_url, wait_until="domcontentloaded", timeout=30000)

    if "/trip/" in parts.path:
        click_load_more_until_done(page)

    page_html = page.content()
    soup = BeautifulSoup(page_html, "html.parser")

    with open(snapshot_path(page_url, outputdir), "w", encoding="utf-8") as f:
        f.write(page_html)

    return soup

def get_emoji_flag( code ):
    """! @brief Convert a FindPenguins flag code into an emoji flag.
    @param code Two-letter country code (`fr`) or subdivision code (`gb-sc`).
    @return Regional-indicator flag, or a tag-sequence flag for subdivisions; None if the code is neither form.
    """

    if len(code) == 2:
        # Use mathematical code point shifting (127397 + ord)
        return chr(127397 + ord(code[0].upper())) + chr(127397 + ord(code[1].upper()))

    # Handle the regional subdivisions (gb-sc, gb-ni)
    elif "-" in code:
        parent, sub = code.split("-", 1)
        
        # Fallback for Northern Ireland since it has no official subdivision emoji
        if parent == "gb" and sub == "ni":
            return chr(127468) + chr(127463)  # Union Jack (🇬🇧)
            
        # Standardize Unicode regional specific variations
        # (e.g., UK uses 'sct' for Scotland, 'wls' for Wales, 'eng' for England)
        if parent == "gb":
            sub_map = {"sc": "sct", "wa": "wls", "wl": "wls", "er": "eng"}
            sub = sub_map.get(sub, sub)
            
        # Generate full tag string payload (e.g., "ustx" or "gbsct")
        full_tag_string = f"{parent}{sub}"
        
        # Assemble the Unicode Tag Sequence 
        flag_sequence = [chr(0x1F3F4)]  # Base Emoji Black Flag
        for char in full_tag_string:
            flag_sequence.append(chr(917536 + ord(char)))  # Tag Shift Offset
        flag_sequence.append(chr(0xE007F))  # Closing Cancel Tag
        
        return "".join(flag_sequence)
        
    return "❓"
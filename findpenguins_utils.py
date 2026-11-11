"""FindPenguins authentication, page loading, and media download helpers."""

import os
import re
import hashlib
import unicodedata
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from findpenguins_config import BASE_URL, LOGIN_PAGE, LOGIN_POST, HEADERS
from common_utils import to_webp

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



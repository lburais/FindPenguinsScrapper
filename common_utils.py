"""Generic XML, text, and image helpers shared by scraper and converter."""

import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from PIL import Image

from common_config import GPX_NS

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



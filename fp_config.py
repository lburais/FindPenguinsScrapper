"""! @file fp_config.py
@brief Central configuration constants for the FindPenguins scraper modules.

This module groups all immutable configuration values used by the scraper,
including endpoint URLs, HTTP headers, and XML namespace URIs.
"""

## @var BASE_URL
## @brief Root URL of the FindPenguins website.
BASE_URL = "https://findpenguins.com"

## @var LOGIN_PAGE
## @brief Login page URL used to obtain CSRF token and cookies.
LOGIN_PAGE = "https://findpenguins.com/login"

## @var LOGIN_POST
## @brief Form POST endpoint used to submit credentials.
LOGIN_POST = "https://findpenguins.com/login/exec"

## @var HEADERS
## @brief Default HTTP headers used by requests and browser context.
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FP-Scraper/1.0)"}

## @var GPX_NS
## @brief GPX 1.1 namespace URI used when creating namespaced tags.
GPX_NS = "http://www.topografix.com/GPX/1/1"

## @var XSI_NS
## @brief XML Schema instance namespace URI used for schemaLocation attribute.
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

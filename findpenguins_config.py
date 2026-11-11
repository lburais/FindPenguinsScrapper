"""FindPenguins endpoints and HTTP defaults."""

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

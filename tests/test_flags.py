import io
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from bs4 import BeautifulSoup
from PIL import Image

from findpenguins_scrapper import download_trip_flags
from fp_parsers import click_footprint_menu, parse_trip_insights, parse_trips
from fp_utils import gpx_tag
from fp_writers import _add_trip_details, build_trip_rst, footprint_to_waypoint


class FlagTests(unittest.TestCase):
    def test_parser_retains_flag_sources_and_strips_title_emoji(self):
        page = Mock()
        page.goto.return_value = SimpleNamespace(ok=True)
        page.content.return_value = """
            <ul id="countryBubbles">
              <li><img src="/flags-png/gb-sc.png">Scotland</li>
              <li><img src="//cdn.example.org/pe.png">Peru</li>
            </ul>
        """
        insights, _ = parse_trip_insights(page, "https://findpenguins.com/u/trip/t", ".", save_html=False)
        self.assertEqual(insights["countries"], [
            {"name": "Scotland", "flag": "https://findpenguins.com/flags-png/gb-sc.png"},
            {"name": "Peru", "flag": "https://cdn.example.org/pe.png"},
        ])
        soup = BeautifulSoup("""
            <div class="tripList"><div class="tripPreviewBox"><a href="/u/trip/t">
              <div class="content"><div class="title"><h2>🇵🇪 Peru 2026</h2></div></div>
            </a></div></div>
        """, "html.parser")
        self.assertEqual(parse_trips(soup, "u")[0]["title"], "Peru 2026")

    def test_popup_flag_source_and_missing_image(self):
        for image, expected in (('<img class="flag-sm" src="/flags-png/gb-ni.png">', "https://findpenguins.com/flags-png/gb-ni.png"), ("", "")):
            with self.subTest(image=image):
                page = Mock()
                locator = Mock()
                locator.count.return_value = 1
                locator.first = locator
                locator.inner_html.return_value = (
                    '<div class="fpMenuPlacesList"><a class="tag" href="/uk">'
                    + image + '🇬🇧 United Kingdom</a></div>'
                )
                page.locator.return_value = locator
                place = click_footprint_menu(page)["places"][0]
                self.assertEqual(place["country"], "United Kingdom")
                self.assertEqual(place["flag"], expected)

    def test_downloads_once_per_url_without_filename_collisions(self):
        image = io.BytesIO()
        Image.new("RGB", (2, 1), "red").save(image, format="PNG")
        response = Mock()
        response.iter_content.return_value = [image.getvalue()]
        countries = [
            {"name": "Peru", "flag": "https://example.test/a/pe.png"},
            {"name": "Other", "flag": "https://example.test/b/pe.png"},
        ]
        footprints = [{"flag": countries[0]["flag"]}]
        with tempfile.TemporaryDirectory() as output, patch("fp_utils.requests.get", return_value=response) as get:
            download_trip_flags(output, {"countries": countries}, footprints)
            self.assertEqual(get.call_count, 2)
            self.assertEqual(footprints[0]["flag"], countries[0]["flag"])
            self.assertNotEqual(countries[0]["flag"], countries[1]["flag"])
            for country in countries:
                self.assertTrue(country["flag"].startswith("flags/"))
                self.assertTrue((Path(output) / country["flag"]).is_file())

    def test_download_failure_is_reported_and_not_referenced(self):
        country = {"name": "Peru", "flag": "https://example.test/pe.png"}
        with tempfile.TemporaryDirectory() as output, \
             patch("fp_utils.requests.get", side_effect=requests.ConnectionError("offline")), \
             patch("builtins.print") as log:
            download_trip_flags(output, {"countries": [country]}, [])
        self.assertEqual(country["flag"], "")
        self.assertIn("offline", str(log.call_args))

    def test_export_copies_shared_flags_and_preserves_countries(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            archive = root / "archive"
            source = archive / "flags/pe-test.webp"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"flag")
            trip_dir = archive / "u/t"
            trip_dir.mkdir(parents=True)
            content = root / "content"
            trip = {
                "slug": "t",
                "title": "🇵🇪 Peru 2026",
                "countries": [{"name": "Peru", "flag": "flags/pe-test.webp"}, {"name": "Chile", "flag": ""}],
            }
            footprints = [{"title": "Lima", "flag": "flags/pe-test.webp", "country": "Peru"}]
            build_trip_rst(str(content), str(trip_dir), {"uid": "u"}, trip, footprints, {"small": 128, "large": 1600})
            trip_rst = (content / "u/t/trip.rst").read_text()
            footprint_rst = (content / "u/t/footprint_1/footprint.rst").read_text()
            self.assertIn(":Title: Peru 2026", trip_rst)
            self.assertIn(":Countries: Peru, Chile", trip_rst)
            self.assertIn(":CountryFlags: Peru|flags/pe-test.webp;Chile|", trip_rst)
            self.assertIn(":Flag: flags/pe-test.webp", footprint_rst)
            self.assertEqual((content / "flags/pe-test.webp").read_bytes(), b"flag")

    def test_gpx_flag_fields_use_the_shared_path(self):
        extensions = ET.Element("extensions")
        _add_trip_details(extensions, {"countries": [{"name": "Peru", "flag": "flags/pe-test.webp"}]})
        self.assertEqual(extensions.findtext("./countries/country/flag"), "flags/pe-test.webp")
        waypoint = footprint_to_waypoint({"lat": "1", "lon": "2", "flag": "flags/pe-test.webp"})
        self.assertEqual(waypoint.findtext(f"{gpx_tag('extensions')}/flag"), "flags/pe-test.webp")


if __name__ == "__main__":
    unittest.main()

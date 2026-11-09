import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

from findpenguins_scrapper import process_profile, scrapper, DEFAULT_SETTINGS
from fp_parsers import parse_trip, parse_trip_insights
from fp_utils import SnapshotError, load_page, snapshot_path


class SkipTests(unittest.TestCase):
    def test_snapshot_round_trip_uses_url_not_title(self):
        page = Mock()
        page.content.return_value = "<h1 class='headline'>Same title</h1><p>one</p>"
        with tempfile.TemporaryDirectory() as directory:
            load_page(page, "https://example.test/u", directory, save_html=True)
            page.reset_mock()
            soup = load_page(page, "https://example.test/u", directory, skip=True)
            self.assertEqual(soup.p.get_text(), "one")
            page.assert_not_called()
            page.goto.assert_not_called()
            with self.assertRaisesRegex(SnapshotError, "No saved HTML"):
                load_page(page, "https://example.test/other", directory, skip=True)
            page.goto.assert_not_called()

    def test_legacy_snapshots_and_ambiguous_footprints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "u.html").write_text("<p>profile</p>")
            (root / "peru-2026.html").write_text("<p>trip</p>")
            footprint = '<li class="footprint" data-id="123"><h1 class="headline">A</h1></li>'
            (root / "old-title.html").write_text(footprint)
            self.assertEqual(load_page(None, "https://example.test/u", directory, skip=True).p.text, "profile")
            self.assertEqual(load_page(None, "https://example.test/u/trip/t", directory, skip=True, title="Peru 2026").p.text, "trip")
            self.assertIsNotNone(load_page(None, "https://example.test/u/footprint/123", directory, skip=True, footprint_id="123").select_one("h1"))
            (root / "other.html").write_text(footprint)
            with self.assertRaisesRegex(SnapshotError, "Multiple saved snapshots"):
                load_page(None, "https://example.test/u/footprint/123", directory, skip=True, footprint_id="123")

    def test_insights_from_snapshot_and_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "insights.html").write_text('<ul id="countryBubbles"><li>Peru</li></ul>')
            insights, _ = parse_trip_insights(None, "https://example.test/u/trip/t", directory, skip=True)
            self.assertEqual(insights["countries"][0]["name"], "Peru")
            (root / "insights.html").unlink()
            with self.assertRaises(SnapshotError):
                parse_trip_insights(None, "https://example.test/u/trip/t", directory, skip=True)

    def test_footprint_popup_saved_and_replayed(self):
        url = "https://findpenguins.com/u/footprint/123"
        trip = BeautifulSoup('<ul class="FootprintList"><li class="footprint" data-id="123"><div class="title"><h2 class="headline"><a href="/u/footprint/123">Lima</a></h2></div></li></ul>', "html.parser")
        html = '<ul class="FootprintList"><li class="footprint" data-id="123"><div class="title"><h1 class="headline"><a>Lima</a></h1></div></li></ul>'
        page = Mock()
        page.content.return_value = html
        popup = {"places": [{"country": "Peru", "flag": "https://example.test/pe.png"}], "overnights": "2"}
        with tempfile.TemporaryDirectory() as directory:
            with patch("fp_parsers.click_footprint_menu", return_value=popup):
                live = parse_trip(page, Mock(), trip, directory, directory, save_html=True)
            replay = parse_trip(None, None, trip, directory, directory, skip=True)
            self.assertEqual(live, replay)
            self.assertEqual(replay[0]["country"], "Peru")
            Path(snapshot_path(url, directory, "popup.json")).write_text("bad json")
            with self.assertRaisesRegex(SnapshotError, "popup snapshot"):
                parse_trip(None, None, trip, directory, directory, skip=True)

    def test_missing_legacy_popup_warns(self):
        url = "https://findpenguins.com/u/footprint/123"
        trip = BeautifulSoup('<ul class="FootprintList"><li class="footprint" data-id="123"><div class="title"><h2 class="headline"><a href="/u/footprint/123">Lima</a></h2></div></li></ul>', "html.parser")
        html = '<li class="footprint" data-id="123"><div class="title"><h1 class="headline"><a>Lima</a></h1></div></li>'
        with tempfile.TemporaryDirectory() as directory:
            Path(snapshot_path(url, directory)).write_text(html)
            with patch("builtins.print") as log:
                footprints = parse_trip(None, None, trip, directory, directory, skip=True)
            self.assertEqual(footprints[0]["country"], "")
            self.assertTrue(any("no saved popup data" in str(call) for call in log.call_args_list))

    def test_skip_overrides_force_and_does_not_login(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profiles = root / "profiles.json"
            profiles.write_text(json.dumps({"user": {"id": "u", "username": "x"}}))
            output = root / "archive"
            (output / "u").mkdir(parents=True)
            marker = output / "u" / "keep.txt"
            marker.write_text("keep")
            settings = {**DEFAULT_SETTINGS, "output": str(output), "trip": None, "save_html": False, "skip": True}
            with patch("findpenguins_scrapper.login") as login, patch("findpenguins_scrapper.create_browser_page") as browser:
                with self.assertRaises(SnapshotError):
                    process_profile("u", "x", "", settings)
                login.assert_not_called()
                browser.assert_not_called()
            with patch("findpenguins_scrapper.process_profile", side_effect=SnapshotError("missing")), \
                 patch("findpenguins_scrapper.clear_folders") as clear:
                with self.assertRaises(SnapshotError):
                    scrapper(str(profiles), str(output), str(root / "content"), force=True, skip=True)
                clear.assert_not_called()
            self.assertEqual(marker.read_text(), "keep")

    def test_profile_replays_all_pages_and_reuses_gpx(self):
        profile_url = "https://findpenguins.com/u"
        trip_url = "https://findpenguins.com/u/trip/t"
        footprint_url = "https://findpenguins.com/u/footprint/123"
        profile_html = """
          <div class="userBox"><div class="nameBox"><h1><a>Alice</a></h1></div></div>
          <div class="tripList"><div class="tripPreviewBox"><a href="/u/trip/t">
          <div class="content"><div class="title"><h2>Trip</h2></div></div>
          </a></div></div>
        """
        trip_html = """
          <div class="tripBox" data-trip-id="99"></div>
          <ul class="FootprintList"><li class="footprint" data-id="123">
          <div class="title"><h2 class="headline"><a href="/u/footprint/123">Lima</a></h2></div>
          </li></ul>
        """
        footprint_html = """
          <li class="footprint" data-id="123"><div class="title">
          <h1 class="headline"><a>Lima</a></h1></div></li>
        """
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            trip_dir = output / "u/t"
            trip_dir.mkdir(parents=True)
            Path(snapshot_path(profile_url, output / "u")).write_text(profile_html)
            Path(snapshot_path(trip_url, trip_dir)).write_text(trip_html)
            Path(snapshot_path(footprint_url, trip_dir)).write_text(footprint_html)
            Path(snapshot_path(footprint_url, trip_dir, "popup.json")).write_text(
                json.dumps({"places": [{"country": "Peru"}]})
            )
            (trip_dir / "insights.html").write_text('<ul id="countryBubbles"><li>Peru</li></ul>')
            gpx = output / "u/t.gpx"
            gpx.write_text('<gpx xmlns="http://www.topografix.com/GPX/1/1"><wpt lat="1" lon="2"><name>Lima</name></wpt></gpx>')
            (trip_dir / "t.gpx").write_text("stale downloaded GPX")
            settings = {**DEFAULT_SETTINGS, "output": str(output), "trip": None, "save_html": False, "skip": True}
            with patch("findpenguins_scrapper.login") as login, \
                 patch("findpenguins_scrapper.create_browser_page") as browser, \
                 patch("findpenguins_scrapper.build_trip_gpx") as build, \
                 patch("findpenguins_scrapper.save_trip_route_map", return_value=""):
                user, trips = process_profile("u", "x", "", settings)
            login.assert_not_called()
            browser.assert_not_called()
            self.assertEqual(user["name"], "Alice")
            self.assertEqual(trips[0]["countries"][0]["name"], "Peru")
            self.assertEqual(trips[0]["footprints"][0]["country"], "Peru")
            self.assertEqual((trips[0]["footprints"][0]["lat"], trips[0]["footprints"][0]["lon"]), ("1", "2"))
            self.assertEqual(build.call_args.args[0], str(gpx))
            self.assertIn('lat="1"', gpx.read_text())
            self.assertEqual((trip_dir / "t.gpx").read_text(), "stale downloaded GPX")


if __name__ == "__main__":
    unittest.main()

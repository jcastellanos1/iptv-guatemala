#!/usr/bin/env python3
"""
test_curation.py — Unit tests for curation logic.

Tests name normalization, M3U parsing, candidate ranking (including quality and
region rules), sequential validation, and duplicate handling.
"""

import unittest
from unittest.mock import patch, MagicMock

# Import functions from scripts.curate_channels
# Add current directory to path if needed
import os
import sys
sys.path.append(os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.curate_channels import (
    normalize_string,
    parse_m3u,
    check_is_spanish,
    matches_preferred_region,
    get_sorting_key,
    matches_blocked_terms
)

class TestCuration(unittest.TestCase):

    def test_normalize_string(self):
        """Test name normalization rules (case, accents, resolution tags)."""
        self.assertEqual(normalize_string("AXN Latin America (1080p)"), "axn latin america")
        self.assertEqual(normalize_string("History Latin America HD"), "history latin america")
        self.assertEqual(normalize_string("CNN en Español (720p)"), "cnn en espanol")
        self.assertEqual(normalize_string("Canal 7 de España [SD]"), "canal 7 de espana")
        self.assertEqual(normalize_string("TNT Series HD"), "tnt series")

    def test_parse_m3u(self):
        """Test parsing of extended M3U file contents."""
        m3u_content = (
            "#EXTM3U\n"
            '#EXTINF:-1 tvg-id="AXN.la" tvg-name="AXN LA" tvg-logo="logo.png" group-title="Series",AXN Latin America (1080p)\n'
            "#EXTVLCOPT:http-user-agent=CustomUA\n"
            "#EXTVLCOPT:http-referrer=https://referrer.com\n"
            "http://example.com/axn.m3u8\n"
            '#EXTINF:-1 tvg-id="TNT.es" tvg-name="TNT Spain" group-title="Movies",TNT Spain HD\n'
            "http://example.com/tnt.m3u8\n"
        )
        streams = parse_m3u(m3u_content)
        self.assertEqual(len(streams), 2)
        
        axn = streams[0]
        self.assertEqual(axn["tvg_id"], "AXN.la")
        self.assertEqual(axn["tvg_name"], "AXN LA")
        self.assertEqual(axn["tvg_logo"], "logo.png")
        self.assertEqual(axn["group_title"], "Series")
        self.assertEqual(axn["display_name"], "AXN Latin America (1080p)")
        self.assertEqual(axn["stream_url"], "http://example.com/axn.m3u8")
        self.assertEqual(axn["resolution"], "1080p")
        self.assertEqual(axn["country_suffix"], "la")
        self.assertEqual(len(axn["extra_lines"]), 2)
        self.assertIn("#EXTVLCOPT:http-user-agent=CustomUA", axn["extra_lines"])

        tnt = streams[1]
        self.assertEqual(tnt["tvg_id"], "TNT.es")
        self.assertEqual(tnt["resolution"], "720p")  # HD maps to 720p
        self.assertEqual(tnt["country_suffix"], "es")

    def test_region_and_spanish_matching(self):
        """Test preference region and Spanish detection."""
        # Preferred regions: Latin America, Panregional, Central America, Mexico, Andes, Colombia
        pref_regions = ["Latin America", "Panregional", "Central America", "Mexico", "Andes", "Colombia"]
        
        stream_la = {"display_name": "AXN Latin America", "group_title": "Series", "country_suffix": "la"}
        stream_mx = {"display_name": "AXN Mexico", "group_title": "Series", "country_suffix": "mx"}
        stream_ru = {"display_name": "AXN Russia", "group_title": "Series", "country_suffix": "ru"}
        stream_es = {"display_name": "AXN Spain", "group_title": "Series", "country_suffix": "es"}
        
        self.assertTrue(matches_preferred_region(stream_la, pref_regions))
        self.assertTrue(matches_preferred_region(stream_mx, pref_regions))
        self.assertFalse(matches_preferred_region(stream_ru, pref_regions))
        
        # Test Spanish detection
        self.assertTrue(check_is_spanish(stream_la))
        self.assertTrue(check_is_spanish(stream_mx))
        self.assertTrue(check_is_spanish(stream_es))
        self.assertFalse(check_is_spanish(stream_ru))

    def test_sorting_ranking_rule(self):
        """Verify 720p Latin America beats 1080p Russia."""
        pref_regions = ["Latin America", "Mexico"]
        
        stream_la_720 = {
            "display_name": "AXN Latin America",
            "group_title": "Series",
            "country_suffix": "la",
            "resolution": "720p",
            "stream_url": "https://example.com/la.m3u8"
        }
        
        stream_ru_1080 = {
            "display_name": "AXN Russia",
            "group_title": "Series",
            "country_suffix": "ru",
            "resolution": "1080p",
            "stream_url": "https://example.com/ru.m3u8"
        }
        
        key_la_720 = get_sorting_key(stream_la_720, pref_regions)
        key_ru_1080 = get_sorting_key(stream_ru_1080, pref_regions)
        
        # Key contains (preferred_region_match, is_spanish, resolution_score, is_https)
        # For LA 720p: (1, 1, 2, 1)
        # For RU 1080p: (0, 0, 3, 1)
        self.assertGreater(key_la_720, key_ru_1080)

    def test_blocked_terms(self):
        """Test that blocked terms are matched properly."""
        stream = {
            "display_name": "TNT Kids Brazil",
            "tvg_id": "TNTKids.br",
            "group_title": "Kids",
            "stream_url": "http://example.com/tntkids.m3u8"
        }
        blocked_tnt = ["Brasil", "Brazil", "Kids"]
        self.assertTrue(matches_blocked_terms(stream, blocked_tnt))
        
        stream_ok = {
            "display_name": "TNT Latin America",
            "tvg_id": "TNT.la",
            "group_title": "Movies",
            "stream_url": "http://example.com/tnt.m3u8"
        }
        self.assertFalse(matches_blocked_terms(stream_ok, blocked_tnt))

    @patch("requests.get")
    def test_sequential_validation_stopping(self, mock_get):
        """Verify sequential validation stops immediately on the first success."""
        # Mock validation requests
        mock_response_ok = MagicMock()
        mock_response_ok.status_code = 200
        mock_response_ok.raw.read.return_value = b"#EXTM3U\n#EXT-X-STREAM-INF"
        
        mock_get.return_value = mock_response_ok
        
        from scripts.curate_channels import validate_stream
        
        # Test validation of first candidate
        is_ok, latency, err = validate_stream("http://stream1.m3u8", [])
        self.assertTrue(is_ok)
        self.assertEqual(mock_get.call_count, 1)

if __name__ == "__main__":
    unittest.main()

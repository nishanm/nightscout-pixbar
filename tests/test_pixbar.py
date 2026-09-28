"""Unit tests for the parts the golden corpus cannot see: the model's rules, the
config layering, the device client's reply handling and the source parsers.

    python -m unittest discover -s tests -v

stdlib only, like everything else here. Network calls are replaced by fakes at
the urllib boundary; nothing in this file touches a device or a source.
"""

import http.client
import io
import json
import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as C  # noqa: E402
import device  # noqa: E402
import faces as F  # noqa: E402
import model as M  # noqa: E402
import render as R  # noqa: E402
import sources  # noqa: E402

FIXED_NOW = 1790510400


class FakeResponse(io.BytesIO):
    """Enough of an HTTPResponse for urlopen's context-manager use."""

    def __init__(self, body=b"", status=200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def fake_urlopen(body=b"{}", raises=None):
    def _open(req, timeout=None, context=None):
        if raises is not None:
            raise raises
        return FakeResponse(body)
    return _open


# ------------------------------------------------------------------ model
class BandTest(unittest.TestCase):
    def test_boundaries_match_the_clocks(self):
        # 55 and 250 are urgent, 70 and 180 are normal - inclusive/exclusive as
        # the TC001 firmware has them, and as the graph rows must agree with.
        self.assertEqual(M.band(55), "urgent")
        self.assertEqual(M.band(56), "warning")
        self.assertEqual(M.band(69), "warning")
        self.assertEqual(M.band(70), "normal")
        self.assertEqual(M.band(180), "normal")
        self.assertEqual(M.band(181), "warning")
        self.assertEqual(M.band(249), "warning")
        self.assertEqual(M.band(250), "urgent")


class DeltaTest(unittest.TestCase):
    def samples(self, *pairs):
        return [M.Sample(FIXED_NOW - age, sgv, "FLAT") for age, sgv in pairs]

    def test_needs_two_samples(self):
        self.assertIsNone(M.delta_for(self.samples((0, 100))))

    def test_dexcom_twin_does_not_zero_the_delta(self):
        # The same reading repeated 11 s later must not make the delta 0.
        s = self.samples((311, 92), (11, 100), (0, 100))
        self.assertEqual(M.delta_for(s), 8)

    def test_moved_both_ways_is_unknown(self):
        s = self.samples((300, 110), (150, 90), (0, 100))
        self.assertIsNone(M.delta_for(s))

    def test_absurd_jump_is_unknown(self):
        s = self.samples((300, 100), (0, 250))
        self.assertIsNone(M.delta_for(s))

    def test_window_excludes_old_samples(self):
        s = self.samples((900, 50), (0, 100))
        self.assertIsNone(M.delta_for(s))


class ReadingTest(unittest.TestCase):
    def test_from_samples_ages_by_rebuilding(self):
        s = [M.Sample(FIXED_NOW - 60 * 3, 118, "FLAT")]
        r1 = M.Reading.from_samples(s, now=FIXED_NOW)
        r2 = M.Reading.from_samples(s, now=FIXED_NOW + 60 * 30)
        self.assertEqual((r1.minutes_ago, r1.stale), (3, False))
        self.assertEqual((r2.minutes_ago, r2.stale), (33, True))
        self.assertEqual(r1.trend_shown, "FLAT")
        self.assertEqual(r2.trend_shown, "NONE")
        self.assertEqual(r2.value_text(), "---")
        self.assertEqual(r2.delta_text(), "")

    def test_unknown_delta_is_a_question_mark_not_zero(self):
        r = M.Reading(100, "FLAT", None, 3)
        self.assertEqual(r.delta_text(), "?")
        self.assertEqual(M.Reading(100, "FLAT", 0, 3).delta_text(), "+0")


# ----------------------------------------------------------------- config
class ConfigTest(unittest.TestCase):
    def load(self, **env):
        with mock.patch.object(C, "LOCAL", "/nonexistent/local.json"), \
             mock.patch.object(C, "CLOCK_STANDARD", "/nonexistent/clock.json"):
            return C.load(environ=env)

    def test_defaults_without_any_file(self):
        cfg = self.load()
        self.assertEqual(cfg["face"], "hero-delta")
        self.assertIsNone(cfg["_credentials_from"])

    def test_env_wins_and_empty_is_ignored(self):
        cfg = self.load(PIXBAR_FACE="clock", PIXBAR_DEXCOM_PASSWORD="",
                        PIXBAR_NIGHTSCOUT_API_SECRET="s3")
        self.assertEqual(cfg["face"], "clock")
        self.assertNotIn("password", cfg.get("dexcom", {}))
        self.assertEqual(cfg["nightscout"]["api_secret"], "s3")
        self.assertEqual(cfg["_credentials_from"], "env")

    def test_bad_int_fails_loudly(self):
        with self.assertRaises(ValueError):
            self.load(PIXBAR_POLL_SECONDS="soon")

    def test_missing_explicit_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.load(NIGHTSCOUT_PIXBAR_CONFIG="/nonexistent/explicit.json")

    def test_describe_never_carries_a_value(self):
        cfg = self.load(PIXBAR_DEXCOM_PASSWORD="hunter2", PIXBAR_NIGHTSCOUT_API_SECRET="s3cret")
        text = C.describe(cfg)
        self.assertNotIn("hunter2", text)
        self.assertNotIn("s3cret", text)
        self.assertIn("dexcom_pass_set=True", text)


# ----------------------------------------------------------------- device
class DeviceTest(unittest.TestCase):
    def setUp(self):
        self.dev = device.Device("198.51.100.9", "night scout")

    def test_json_reply_is_parsed_and_app_name_quoted(self):
        seen = {}

        def _open(req, timeout=None, context=None):
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            return FakeResponse(b'{"code":200,"message":"app switch requested"}')
        with mock.patch("urllib.request.urlopen", _open):
            reply = self.dev.switch_to()
        self.assertEqual(reply["code"], 200)
        self.assertEqual(seen["method"], "POST")
        self.assertIn("name=night%20scout", seen["url"])

    def test_non_json_reply_is_wrapped_not_raised(self):
        with mock.patch("urllib.request.urlopen", fake_urlopen(b"<html>settings</html>")):
            self.assertEqual(self.dev.get("/x"), {"raw": "<html>settings</html>"})

    def test_transport_and_http_exceptions_become_device_errors(self):
        for exc in (urllib.error.URLError("refused"), http.client.RemoteDisconnected("cut"),
                    TimeoutError()):
            with mock.patch("urllib.request.urlopen", fake_urlopen(raises=exc)):
                with self.assertRaises(device.DeviceError):
                    self.dev.get("/getBase")
                self.assertFalse(self.dev.app_exists())

    def test_oversized_reply_is_refused(self):
        with mock.patch("urllib.request.urlopen", fake_urlopen(b"x" * (device.MAX_REPLY + 1))):
            with self.assertRaises(device.DeviceError):
                self.dev.get("/getBase")

    def test_app_exists_reads_the_list(self):
        with mock.patch("urllib.request.urlopen", fake_urlopen(b'{"apps":["night scout"],"count":1}')):
            self.assertTrue(self.dev.app_exists())
        with mock.patch("urllib.request.urlopen", fake_urlopen(b'{"apps":[],"count":0}')):
            self.assertFalse(self.dev.app_exists())


# ---------------------------------------------------------------- sources
class TrendTest(unittest.TestCase):
    def test_spellings_and_indices(self):
        self.assertEqual(sources.parse_trend("FortyFiveDown"), "FORTY_FIVE_DOWN")
        self.assertEqual(sources.parse_trend("NONE COMPUTABLE"), "NONE")
        self.assertEqual(sources.parse_trend("nonecomputable"), "NONE")
        self.assertEqual(sources.parse_trend(4), "FLAT")
        self.assertEqual(sources.parse_trend(None), "NONE")
        self.assertEqual(sources.parse_trend("banana"), "NONE")
        for name in M.TRENDS:
            self.assertEqual(sources.parse_trend(name.replace("_", "")), name)


class NightscoutTest(unittest.TestCase):
    def test_parses_sgv_entries_and_asks_for_sgv_only(self):
        body = json.dumps([
            {"type": "sgv", "sgv": 118, "date": (FIXED_NOW - 60) * 1000, "direction": "Flat"},
            {"type": "cal", "date": (FIXED_NOW - 30) * 1000},
            {"type": "sgv", "sgv": 115, "date": (FIXED_NOW - 360) * 1000, "direction": "FortyFiveUp"},
        ]).encode()
        seen = {}

        def _open(req, timeout=None, context=None):
            seen["url"] = req.full_url
            seen["secret"] = req.get_header("Api-secret")
            return FakeResponse(body)
        ns = sources.Nightscout("http://ns.example", api_secret="abc")
        with mock.patch("urllib.request.urlopen", _open):
            got = ns.fetch()
        self.assertEqual([s.sgv for s in got], [115, 118])           # sorted, cal skipped
        self.assertEqual(got[-1].trend, "FLAT")
        self.assertIn("find[type]=sgv", seen["url"])
        self.assertEqual(len(seen["secret"]), 40)                    # sha1 hex, never the secret
        self.assertNotIn("abc", seen["url"])

    def test_html_200_is_bad_data_not_a_crash(self):
        ns = sources.Nightscout("http://ns.example")
        with mock.patch("urllib.request.urlopen", fake_urlopen(b"<html>maintenance</html>")):
            with self.assertRaises(sources.SourceError) as cm:
                ns.fetch()
        self.assertEqual(cm.exception.reason, "BAD DATA")
        self.assertFalse(cm.exception.fatal)

    def test_401_is_fatal_and_cut_connection_is_not(self):
        ns = sources.Nightscout("http://ns.example")
        err = urllib.error.HTTPError("http://ns.example", 401, "nope", {}, io.BytesIO(b""))
        with mock.patch("urllib.request.urlopen", fake_urlopen(raises=err)):
            with self.assertRaises(sources.SourceError) as cm:
                ns.fetch()
        self.assertTrue(cm.exception.fatal)
        with mock.patch("urllib.request.urlopen",
                        fake_urlopen(raises=http.client.RemoteDisconnected("cut"))):
            with self.assertRaises(sources.SourceError) as cm:
                ns.fetch()
        self.assertFalse(cm.exception.fatal)


class DexcomTest(unittest.TestCase):
    def test_locked_or_wrong_password_is_fatal(self):
        dx = sources.DexcomShare("u", "p", "us")
        for marker in ("SSO_AuthenticatePasswordInvalid", "SSO_AuthenticateMaxAttemptsExceeed",
                       "AccountPasswordInvalid"):
            err = urllib.error.HTTPError("https://x", 500, "err", {},
                                         io.BytesIO(json.dumps({"Code": marker}).encode()))
            with mock.patch("urllib.request.urlopen", fake_urlopen(raises=err)):
                with self.assertRaises(sources.SourceError) as cm:
                    dx.fetch()
            self.assertTrue(cm.exception.fatal, marker)

    def test_readings_parse_and_sort(self):
        dx = sources.DexcomShare("u", "p", "us")
        dx.account_id, dx.session_id = "acc", "sess"
        body = json.dumps([
            {"ST": f"/Date({(FIXED_NOW - 60) * 1000})/", "Value": 120, "Trend": "Flat"},
            {"ST": f"/Date({(FIXED_NOW - 360) * 1000})/", "Value": 125, "Trend": 5},
        ]).encode()
        with mock.patch("urllib.request.urlopen", fake_urlopen(body)):
            got = dx.fetch()
        self.assertEqual([s.sgv for s in got], [125, 120])
        self.assertEqual(got[0].trend, "FORTY_FIVE_DOWN")


# ------------------------------------------------------------------ faces
class FacesTest(unittest.TestCase):
    def test_registry_covers_every_state_without_clipping(self):
        frames = list(F.every_frame(now=FIXED_NOW))
        self.assertEqual(len(frames), len(F.FACES) * len(F.STATE_NAMES))
        self.assertEqual([p.clipped for *_, p in frames], [0] * len(frames))

    def test_graph_row_zone_agrees_with_colour_at_the_thresholds(self):
        # Exactly 180 is green and must plot in the normal rows; exactly 55 is
        # red and must plot in the urgent-low rows. This was wrong once.
        bands = F._bands(0, 15)
        for sgv in (55, 56, 69, 70, 180, 181, 249, 250):
            zone = F._zone(sgv)
            self.assertEqual(zone.split("-")[0], M.band(sgv), sgv)
            lo, hi, first, last = bands[zone]
            self.assertTrue(first <= F.row_for(sgv, bands) <= last, sgv)

    def test_demo_states_are_deterministic_for_a_pinned_now(self):
        a = [R.raw_rgb(p) for *_, p in F.every_frame(now=FIXED_NOW)]
        b = [R.raw_rgb(p) for *_, p in F.every_frame(now=FIXED_NOW)]
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()

"""Run with:  python -m unittest -v   (uses offline demo weather, no internet needed)"""
import unittest
from datetime import timedelta

import alerts
import engine as E
from allocator import allocate

TODAY = E.today_ist()


def field(**kw):
    f = dict(name="F", crop="sugarcane", sowing_date=str(TODAY - timedelta(days=200)),
             area_acre=2, soil="black", irrigation="flood", lat=17.98, lon=74.43,
             last_irrigation=str(TODAY - timedelta(days=12)), pump_lpm=400)
    f.update(kw)
    return f


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.w = E.get_weather(17.98, 74.43, offline=True)

    def test_kc_curve(self):
        self.assertAlmostEqual(E.kc_for("sugarcane", 0), 0.40)
        self.assertAlmostEqual(E.kc_for("sugarcane", 150), 1.25)
        self.assertTrue(0.40 < E.kc_for("sugarcane", 60) < 1.25)
        self.assertLess(E.kc_for("sugarcane", 350), 1.25)

    def test_depletion_bounds_and_sane_water(self):
        r = E.recommend(field(), weather=self.w)
        self.assertTrue(0 <= r["depletion_mm"] <= r["taw_mm"])
        self.assertLess(r["etc_today"], 10)          # a few mm/day, not hundreds
        self.assertLess(r["water_mm"], r["taw_mm"] / 0.6 + 1)

    def test_long_dry_gap_triggers_irrigation(self):
        dry = dict(self.w, rain=[0.0] * len(self.w["rain"]), prob=[0] * len(self.w["prob"]))
        r = E.recommend(field(last_irrigation=str(TODAY - timedelta(days=29))), weather=dry)
        self.assertEqual(r["action"], "IRRIGATE_NOW")
        self.assertGreater(r["litres"], 0)
        self.assertGreater(r["minutes"], 0)

    def test_just_irrigated_needs_nothing(self):
        r = E.recommend(field(last_irrigation=str(TODAY)), weather=self.w)
        self.assertEqual(r["action"], "NO_NEED")
        self.assertEqual(r["litres"], 0)

    def test_rain_flips_to_wait(self):
        dry = dict(self.w, rain=[0.0] * len(self.w["rain"]), prob=[0] * len(self.w["prob"]))
        f = field(last_irrigation=str(TODAY - timedelta(days=29)))
        self.assertEqual(E.recommend(f, weather=dry)["action"], "IRRIGATE_NOW")
        r = E.recommend(f, weather=dry, simulate_rain=True)
        self.assertEqual(r["action"], "WAIT")
        self.assertEqual(r["litres"], 0)
        self.assertGreater(r["litres_if_irrigated"], 0)   # water saved by waiting

    def test_sensor_override(self):
        r = E.recommend(field(sensor_depletion_mm=500), weather=self.w)
        self.assertLessEqual(r["depletion_mm"], r["taw_mm"])
        self.assertIn(r["action"], ("IRRIGATE_NOW", "WAIT"))

    def test_not_sown_and_season_over(self):
        self.assertEqual(E.recommend(field(sowing_date=str(TODAY + timedelta(days=5))), weather=self.w)["action"], "NOT_SOWN")
        self.assertEqual(E.recommend(field(sowing_date=str(TODAY - timedelta(days=900))), weather=self.w)["action"], "SEASON_OVER")

    def test_drip_more_efficient_than_flood(self):
        dry = dict(self.w, rain=[0.0] * len(self.w["rain"]), prob=[0] * len(self.w["prob"]))
        a = E.recommend(field(irrigation="flood", sensor_depletion_mm=160), weather=dry)
        b = E.recommend(field(irrigation="drip", sensor_depletion_mm=160), weather=dry)
        self.assertLess(b["litres"], a["litres"])

    def test_priority_and_allocation(self):
        dry = dict(self.w, rain=[0.0] * len(self.w["rain"]), prob=[0] * len(self.w["prob"]))
        fs = [field(name="Stressed", sensor_depletion_mm=170),
              field(name="Fine", last_irrigation=str(TODAY)),
              field(name="Less", crop="wheat", sowing_date=str(TODAY - timedelta(days=60)), sensor_depletion_mm=95)]
        for f in fs:
            f["reco"] = E.recommend(f, weather=dry)
        ranked = E.priority(fs)
        self.assertEqual(ranked[0]["name"], "Stressed")
        need = ranked[0]["reco"]["litres"]
        rows, left = allocate(ranked, need // 2)
        self.assertEqual(rows[0]["status"], "partial")
        self.assertEqual(left, 0)
        rows, left = allocate(ranked, 10 ** 9)
        self.assertEqual(rows[0]["status"], "full")
        self.assertGreater(left, 0)

    def test_savings(self):
        s = E.water_savings(field(), self.w, habit_days=7, habit_mm=40)
        self.assertGreaterEqual(s["smart_litres"], 0)
        self.assertEqual(s["saved_litres"], s["habit_litres"] - s["smart_litres"])

    def test_alerts_marathi(self):
        f = field(last_irrigation=str(TODAY - timedelta(days=29)))
        dry = dict(self.w, rain=[0.0] * len(self.w["rain"]), prob=[0] * len(self.w["prob"]))
        f["reco"] = E.recommend(f, weather=dry)
        m = alerts.message(f, "mr")
        self.assertIn("पाणी द्या", m)
        self.assertEqual(alerts.mr_digits("45"), "४५")
        ok, _ = alerts.send_telegram("x", token=None, chat_id=None)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()

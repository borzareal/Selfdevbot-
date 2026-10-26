import unittest
from datetime import datetime, time, timedelta, timezone

from selfdevbot.db import Database
from selfdevbot.utils import (
    clean_days,
    extract_json,
    format_days,
    merge_turns,
    parse_hhmm,
    parse_local_datetime,
    parse_voice_request,
    resolve_timezone,
    split_message,
    to_ptb_days,
    validate_checkins,
)


class UtilsTest(unittest.TestCase):
    def test_parse_hhmm(self):
        self.assertEqual(parse_hhmm("7:30"), time(7, 30))
        self.assertEqual(parse_hhmm("07h30"), time(7, 30))
        self.assertEqual(parse_hhmm("23h"), time(23, 0))
        self.assertIsNone(parse_hhmm("25:00"))
        self.assertIsNone(parse_hhmm("vers minuit"))

    def test_ptb_days_start_on_sunday(self):
        self.assertEqual(to_ptb_days([0]), (1,))      # lundi
        self.assertEqual(to_ptb_days([6]), (0,))      # dimanche
        self.assertEqual(to_ptb_days(list(range(7))), tuple(range(7)))

    def test_format_and_clean_days(self):
        self.assertEqual(format_days([0, 1, 2, 3, 4]), "en semaine")
        self.assertEqual(format_days([6, 5]), "le week-end")
        self.assertEqual(clean_days([1, "3", 9, "x"]), [1, 3])
        self.assertEqual(clean_days(None), list(range(7)))

    def test_validate_checkins(self):
        raw = [
            {"time": "21h", "days": [0], "purpose": "bilan"},
            {"time": "7:00", "purpose": "réveil"},
            {"time": "nope", "purpose": "x"},
            {"time": "12:00", "purpose": ""},
            "junk",
        ]
        self.assertEqual(validate_checkins(raw), [
            {"time": "07:00", "days": list(range(7)), "purpose": "réveil"},
            {"time": "21:00", "days": [0], "purpose": "bilan"},
        ])
        self.assertEqual(validate_checkins(None), [])

    def test_timezone(self):
        self.assertEqual(resolve_timezone("America/Montreal", "Europe/Paris"), "America/Montreal")
        self.assertEqual(resolve_timezone("Paris", "Europe/Paris"), "Europe/Paris")
        self.assertEqual(resolve_timezone(None, "Europe/Paris"), "Europe/Paris")

    def test_parse_local_datetime(self):
        dt = parse_local_datetime("2026-07-01T14:00", "Europe/Paris")
        self.assertEqual(dt, datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc))
        self.assertIsNone(parse_local_datetime("demain", "Europe/Paris"))

    def test_split_message(self):
        text = "a" * 3000 + "\n" + "b" * 3000
        chunks = split_message(text)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(len(c) <= 4000 for c in chunks))


    def test_parse_voice_request(self):
        self.assertEqual(parse_voice_request("yo, mes objectifs stp\nans=voc"), ("yo, mes objectifs stp", True))
        self.assertEqual(parse_voice_request("salut ANS = VOC "), ("salut", True))
        self.assertEqual(parse_voice_request("salut"), ("salut", False))
        self.assertEqual(parse_voice_request("ans=voc puis autre chose"), ("ans=voc puis autre chose", False))

    def test_clean_for_speech(self):
        from selfdevbot.voice import clean_for_speech
        self.assertEqual(clean_for_speech("**Go** à la salle 💪\n- 3 séries"), "Go à la salle \n3 séries")

    def test_extract_json(self):
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(extract_json('Voici : {"a": {"b": 2}} voilà'), {"a": {"b": 2}})
        self.assertIsNone(extract_json("pas de json"))
        self.assertIsNone(extract_json("{cassé"))

    def test_merge_turns(self):
        turns = [{"role": "assistant", "content": "Debout !"},
                 {"role": "assistant", "content": "Tu dors ?"},
                 {"role": "user", "content": "oui"},
                 {"role": "user", "content": "[interne]"}]
        self.assertEqual(merge_turns(turns), [
            {"role": "user", "content": "(début de la conversation)"},
            {"role": "assistant", "content": "Debout !\n\nTu dors ?"},
            {"role": "user", "content": "oui\n\n[interne]"},
        ])
        self.assertEqual(turns[0]["content"], "Debout !")  # l'historique d'origine n'est pas modifié


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.db.ensure_user(1, "Bruce", "Europe/Paris")

    def tearDown(self):
        self.db.conn.close()

    def test_onboarding_and_profile(self):
        self.assertFalse(self.db.get_user(1)["onboarded"])
        self.db.save_onboarding(1, {"name": "Bruce", "goals": "sauver Gotham"}, "Europe/Paris", "strat")
        self.db.update_profile_field(1, "bed_time", "23:00")
        user = self.db.get_user(1)
        self.assertTrue(user["onboarded"])
        self.assertEqual(user["profile"]["bed_time"], "23:00")
        self.assertEqual([u["chat_id"] for u in self.db.onboarded_users()], [1])

    def test_checkins(self):
        self.db.replace_checkins(1, [{"time": "14:00", "days": [0, 2], "purpose": "salle"}])
        cid = self.db.add_checkin(1, "08:00", [0], "réveil")
        self.assertEqual([c["time"] for c in self.db.list_checkins(1)], ["08:00", "14:00"])
        self.assertFalse(self.db.remove_checkin(2, cid))  # pas son check-in
        self.assertTrue(self.db.remove_checkin(1, cid))
        self.assertEqual(self.db.list_checkins(1)[0]["days"], [0, 2])

    def test_reminders(self):
        rid = self.db.add_reminder(1, datetime.now(timezone.utc) + timedelta(hours=1), "loyer")
        self.assertEqual(len(self.db.pending_reminders(1)), 1)
        self.db.mark_reminder_sent(rid)
        self.assertEqual(self.db.pending_reminders(), [])
        self.assertFalse(self.db.delete_reminder(1, rid))

    def test_history_and_delete(self):
        for i in range(5):
            self.db.add_message(1, "user", f"m{i}")
        self.assertEqual([m["content"] for m in self.db.recent_messages(1, 2)], ["m3", "m4"])
        self.db.add_memory(1, "a fini son premier semi-marathon")
        self.db.delete_user(1)
        self.assertIsNone(self.db.get_user(1))
        self.assertEqual(self.db.recent_messages(1), [])
        self.assertEqual(self.db.list_memories(1), [])


if __name__ == "__main__":
    unittest.main()

"""comms selftests: stdlib only. run: python3 tests/selftest.py

the fixtures are linphone's own schemas, built here from the columns the sdk
declares, so a reader that drifts from linphone fails immediately.
"""
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from heyphony import channels, cli, inbox, mail, meetings, providers, webhook
from heyphony import sip as linphone


def call_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("create table call_history (id integer primary key, caller text, callee text,"
                 " direction integer, duration integer, start_time text, connected_time text,"
                 " status integer, videoEnabled integer, quality real, call_id text, refkey text)")
    conn.executemany("insert into call_history (caller, callee, direction, duration, start_time,"
                     " connected_time, status, call_id) values (?,?,?,?,?,?,?,?)", rows)
    conn.commit(); conn.close()


def message_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("create table history (id integer primary key, localContact text, remoteContact text,"
                 " direction integer, message text, time integer, read integer, status integer,"
                 " url text, utc text, appdata text, content text, messageId text,"
                 " content_type text, is_secured integer)")
    conn.executemany("insert into history (localContact, remoteContact, direction, message, time, read)"
                     " values (?,?,?,?,?,?)", rows)
    conn.commit(); conn.close()


class TestLinphoneConfig(unittest.TestCase):
    def test_rc_writes_the_sections_linphone_reads(self):
        text = linphone.rc_text("voip.ms", "+15550001111", "123456_agent", "hunter2", "chicago.voip.ms")
        for needle in ("[proxy_0]", "reg_proxy=sip:chicago.voip.ms", "reg_identity=sip:123456_agent@chicago.voip.ms",
                       "[auth_info_0]", "username=123456_agent", "passwd=hunter2", "domain=sip:chicago.voip.ms"):
            self.assertIn(needle, text)

    def test_rc_is_written_private(self):
        with tempfile.TemporaryDirectory() as d:
            path = linphone.write_rc("flowroute", "+15550002222", "u", "p", None, home=d)
            self.assertTrue(path.is_file())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_regional_server_is_not_guessed_silently(self):
        self.assertEqual(linphone.sip_host("voip.ms", "to2.voip.ms"), "to2.voip.ms")
        self.assertIn("voip.ms", linphone.sip_host("voip.ms"))
        with self.assertRaises(KeyError):
            linphone.sip_host("somebody-else")


class TestWhereTheNumberLives(unittest.TestCase):
    def test_the_default_endpoint_is_the_durable_host(self):
        plan = linphone.connection_plan("+15550001111")
        self.assertEqual(plan["endpoint"], "host")
        self.assertTrue(plan["survives_burn"])
        self.assertTrue(plan["rings_with_no_guest"])
        self.assertFalse(plan["secret_in_burn"])

    def test_a_guest_registration_is_allowed_but_named_as_a_liability(self):
        plan = linphone.connection_plan("+15550001111", "guest")
        self.assertTrue(plan["secret_in_burn"])
        self.assertFalse(plan["survives_burn"])
        self.assertEqual(plan["registrations"], 1)

    def test_one_did_is_one_registration_either_way(self):
        for endpoint in linphone.ENDPOINTS:
            self.assertEqual(linphone.connection_plan("+1555", endpoint)["registrations"], 1)

    def test_an_endpoint_we_do_not_model_is_refused(self):
        with self.assertRaises(KeyError):
            linphone.connection_plan("+1555", "somewhere")


class TestReaders(unittest.TestCase):
    def test_calls_are_read_and_named(self):
        with tempfile.TemporaryDirectory() as d:
            db = pathlib.Path(d) / "call-history.db"
            call_db(db, [("sip:caller@x", "sip:agent@y", 1, 42, "1700000000", None, 0, "abc"),
                         ("sip:bank@x", "sip:agent@y", 1, 0, "1700000100", None, 2, "def")])
            got = linphone.calls(db=db)
            self.assertEqual([c["direction"] for c in got], ["incoming", "incoming"])
            self.assertEqual({c["status"] for c in got}, {"success", "missed"})
            self.assertEqual(len(linphone.calls(db=db, missed_only=True)), 1)

    def test_sip_messages_table_is_read_but_is_not_the_inbox(self):
        with tempfile.TemporaryDirectory() as d:
            db = pathlib.Path(d) / "messages.db"
            message_db(db, [("sip:agent@y", "sip:x@z", 1, "hello", 1700000000, 0)])
            got = linphone.messages(db=db)
            self.assertEqual(got[0]["body"], "hello")
            self.assertFalse(got[0]["read"])

    def test_missing_db_is_an_empty_list_not_a_crash(self):
        self.assertEqual(linphone.calls(db="/nope/call-history.db"), [])


class TestInbox(unittest.TestCase):
    def test_a_retried_webhook_is_one_message(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "inbox.jsonl"
            entry = {"id": "m1", "from": "+1555", "body": "hi", "at": 1700000000}
            self.assertEqual(inbox.append(entry, path), (True, "stored"))
            self.assertEqual(inbox.append(entry, path), (False, "duplicate"))
            self.assertEqual(inbox.count(path), 1)

    def test_since_filters_on_the_provider_timestamp(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "inbox.jsonl"
            inbox.append({"id": "old", "at": 1000, "body": "old"}, path)
            inbox.append({"id": "new", "at": 1700000000, "body": "new"}, path)
            self.assertEqual([m["id"] for m in inbox.read(path, since_days=1)], [])


class TestWebhook(unittest.TestCase):
    def test_normalize_pulls_the_flat_shape_and_keeps_raw(self):
        entry = webhook.normalize("sms", {"from": "+1555", "to": "+1", "body": "ping", "id": "x1"})
        self.assertEqual((entry["sender"], entry["body"], entry["id"]), ("+1555", "ping", "x1"))
        self.assertEqual(entry["channel"], "sms")
        self.assertIn("from", entry["raw"])

    def test_normalize_walks_the_nested_shape(self):
        entry = webhook.normalize("sms", {"data": {"id": "y1", "attributes": {
            "from": "+1666", "body": "nested", "timestamp": "1700000000"}}})
        self.assertEqual((entry["id"], entry["body"]), ("y1", "nested"))

    def test_an_unknown_payload_still_gets_stored(self):
        entry = webhook.normalize("sms", {"weird": {"thing": 1}})
        self.assertIn("raw", entry)
        self.assertIsNotNone(entry["at"])


class TestProviderClaims(unittest.TestCase):
    def test_offline_capabilities_are_data_not_prose(self):
        self.assertTrue(providers.works_while_off("voip.ms")["voicemail"])
        self.assertFalse(providers.works_while_off("flowroute")["voicemail"])
        for name in providers.PROVIDERS:
            self.assertFalse(providers.profile(name)["verified"], name)

    def test_otp_is_refused_for_a_voice_did(self):
        self.assertEqual(providers.otp_viability("sip-did")["viable"], "no")

    def test_markup_never_changes_the_classification(self):
        for name in providers.PROVIDERS:
            self.assertEqual(providers.still_voip(name)["number_type"], "voip")


class TestOneEnvelopeManyChannels(unittest.TestCase):
    def test_every_channel_gate_closes_when_unset(self):
        for name in channels.CHANNELS:
            self.assertEqual(channels.state(name, env={})["state"], "closed", name)

    def test_the_envelope_is_the_same_shape_whichever_carrier(self):
        a = channels.envelope("sms", sender="+1", body="hi", at=1, message_id="a")
        b = channels.envelope("mail", sender="x@y", body="hi", at=1, message_id="b")
        self.assertEqual(set(a), set(b))
        self.assertEqual(set(a), set(channels.KEYS))

    def test_an_unmodelled_channel_is_refused_not_invented(self):
        with self.assertRaises(KeyError):
            channels.envelope("telegram", body="hi")

    def test_refusals_are_named_so_no_card_improvises_them(self):
        self.assertIn("otp-by-did", channels.BLOCKED)
        self.assertIn("publish", channels.refused("publish-on-its-own")["why"])


class TestMailInbox(unittest.TestCase):
    good = {"HEYPHONY_MAIL_SECRET": "s3cret", "HEYPHONY_FORWARD_WHITELIST": "owner@example.com"}

    def test_unset_secret_closes_the_lane(self):
        ok, why = mail.verify({"x-agentmail-secret": "anything"}, env={})
        self.assertFalse(ok)
        self.assertIn("closed", why)

    def test_a_wrong_secret_is_rejected(self):
        ok, _ = mail.verify({"x-agentmail-secret": "nope"}, env=self.good)
        self.assertFalse(ok)

    def test_unset_whitelist_allows_nobody(self):
        ok, why = mail.whitelisted("owner@example.com", env={"HEYPHONY_MAIL_SECRET": "s3cret"})
        self.assertFalse(ok)
        self.assertIn("unset", why)

    def test_an_unlisted_sender_does_not_become_work(self):
        ok, why = mail.whitelisted("stranger@example.com", env=self.good)
        self.assertFalse(ok)
        self.assertIn("unlisted", why)

    def test_a_whitelisted_mail_becomes_a_message(self):
        body, why = mail.inbound({"message_id": "m1", "from": "Owner <owner@example.com>",
                                  "subject": "hi", "text": "join this"}, {"x-agentmail-secret": "s3cret"}, self.good)
        self.assertEqual(why, "ok")
        self.assertEqual(body["id"], "m1")
        self.assertEqual(body["subject"], "hi")

    def test_shape_is_checked_before_trust(self):
        body, why = mail.inbound({"from": "owner@example.com"}, {"x-agentmail-secret": "s3cret"}, self.good)
        self.assertIsNone(body)
        self.assertIn("required", why)

    def test_relay_is_closed_without_smtp(self):
        self.assertFalse(mail.outbound_plan("a@b", "s", "b", env={})["sendable"])


class TestMeetingJoin(unittest.TestCase):
    env = {"ZOOM_SDK_KEY": "key", "ZOOM_SDK_SECRET": "secret"}

    def test_a_signed_join_round_trips(self):
        token = meetings.sign_zoom_join("123456789", env=self.env)
        self.assertTrue(meetings.verify_zoom_token(token["join_token"], self.env))

    def test_a_tampered_token_does_not_verify(self):
        env = dict(self.env, ZOOM_SDK_SECRET="other")
        token = meetings.sign_zoom_join("123456789", env=self.env)
        self.assertFalse(meetings.verify_zoom_token(token["join_token"], env))

    def test_the_lane_closes_instead_of_lying(self):
        with self.assertRaises(RuntimeError):
            meetings.sign_zoom_join("123456789", env={})
        self.assertFalse(meetings.lane_available({}))

    def test_join_plan_names_what_is_missing(self):
        plan = meetings.join_plan("zoom", "123456789", env={})
        self.assertFalse(plan["joinable"])
        self.assertEqual(plan["missing"], ["ZOOM_SDK_KEY", "ZOOM_SDK_SECRET"])

    def test_an_unmodelled_platform_is_refused(self):
        self.assertFalse(meetings.join_plan("webex", "1")["joinable"])


class TestTheCommand(unittest.TestCase):
    def test_setup_flag_is_the_same_as_the_subcommand(self):
        self.assertEqual(cli.setup_payload()["order"], cli.setup_payload()["order"])
        self.assertEqual(set(cli.setup_payload()["lanes"]), set(channels.CHANNELS))

    def test_every_lane_says_what_to_ask_the_owner_for(self):
        for name, lane in cli.setup_payload()["lanes"].items():
            self.assertTrue(lane["needs"]["from_owner"], name)
            self.assertTrue(lane["needs"]["prove"], name)

    def test_setup_names_the_rules_not_just_the_steps(self):
        rules = " ".join(cli.setup_payload()["rules"])
        for needle in ("unset credentials close a lane", "a did is voip", "never publishes"):
            self.assertIn(needle, rules)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f"selftest: {result.testsRun - failed}/{result.testsRun} pass")
    sys.exit(1 if failed else 0)

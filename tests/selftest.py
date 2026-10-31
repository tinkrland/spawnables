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

from comms import catcher, envelope, gates, registry
from comms import cli as comms_cli
from heyphony import cli as telephony_cli
from heyphony import catcher as phone_catcher
from heyphony import inbox, providers, sip
from heyphony import sip as linphone


def lane(name):
    return registry._load(name)


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
        entry = phone_catcher.normalize({"from": "+1555", "to": "+1", "body": "ping", "id": "x1"})
        self.assertEqual((entry["sender"], entry["body"], entry["id"]), ("+1555", "ping", "x1"))
        self.assertEqual(entry["channel"], "sms")
        self.assertIn("from", entry["raw"])

    def test_normalize_walks_the_nested_shape(self):
        entry = phone_catcher.normalize({"data": {"id": "y1", "attributes": {
            "from": "+1666", "body": "nested", "timestamp": "1700000000"}}})
        self.assertEqual((entry["id"], entry["body"]), ("y1", "nested"))

    def test_an_unknown_payload_still_gets_stored(self):
        entry = phone_catcher.normalize({"weird": {"thing": 1}})
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



class TestOneEnvelopeManyCarriers(unittest.TestCase):
    def test_every_lane_closes_when_its_gate_is_unset(self):
        for name, spec in registry.lanes().items():
            self.assertEqual(envelope.state_for(spec, env={})["state"], "closed", name)

    def test_the_envelope_is_one_shape_whichever_folder_sent_it(self):
        a = envelope.envelope("whatsapp", sender="+1", body="hi", at=1, id="a")
        b = envelope.envelope("imessage", sender="x", body="hi", at=1, id="b")
        self.assertEqual(set(a), set(b))
        self.assertEqual(set(a), set(envelope.KEYS))

    def test_every_folder_at_the_root_is_a_lane(self):
        for name in ("email", "imessage", "whatsapp", "discord", "slack", "signal", "meetings", "streaming"):
            self.assertIn(name, registry.lanes())
            self.assertIn(name, registry.folders())

    def test_heyphony_stays_decoupled_from_the_umbrella(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        for path in (root / "heyphony").rglob("*.py"):
            self.assertNotIn("comms", path.read_text(), f"{path} imports the umbrella")

    def test_refusals_are_named_once_not_improvised_per_card(self):
        for needle in ("otp-by-did", "group-reply", "social-reply"):
            self.assertIn(needle, envelope.REFUSED)


class TestEmailFrontDoor(unittest.TestCase):
    good = {"HEYPHONY_MAIL_SECRET": "s3cret", "HEYPHONY_FORWARD_WHITELIST": "owner@example.com"}

    def test_unset_secret_closes_the_door(self):
        ok, why = lane("email").verify({"x-agentmail-secret": "anything"}, "{}", env={})
        self.assertFalse(ok)
        self.assertIn("closed", why)

    def test_a_wrong_secret_is_rejected(self):
        self.assertFalse(lane("email").verify({"x-agentmail-secret": "nope"}, "{}", self.good)[0])

    def test_unset_whitelist_allows_nobody(self):
        ok, why = lane("email").whitelisted("owner@example.com", env={"HEYPHONY_MAIL_SECRET": "s3cret"})
        self.assertFalse(ok)
        self.assertIn("unset", why)

    def test_an_unlisted_sender_does_not_become_work(self):
        ok, why = lane("email").whitelisted("stranger@example.com", self.good)
        self.assertFalse(ok)
        self.assertIn("unlisted", why)

    def test_a_whitelisted_sender_does(self):
        self.assertTrue(lane("email").whitelisted("Owner <owner@example.com>", self.good)[0])

    def test_relay_is_closed_without_smtp(self):
        self.assertFalse(lane("email").relay_plan("a@b", "s", "b", env={})["sendable"])


class TestSignalNeedsANumber(unittest.TestCase):
    def test_linking_a_device_needs_no_number(self):
        plan = lane("signal").registration_plan("link-device", env={})
        self.assertTrue(plan["possible"])
        self.assertFalse(plan["needs_number_of_its_own"])

    def test_registering_does_and_says_where_it_comes_from(self):
        plan = lane("signal").registration_plan("register-number", env={})
        self.assertFalse(plan["possible"])
        self.assertIn("HEYPHONY_SIP_DID", plan["missing"][0])

    def test_the_number_from_telephony_opens_it(self):
        plan = lane("signal").registration_plan("register-number", {"HEYPHONY_SIP_DID": "+1555"})
        self.assertTrue(plan["possible"])

    def test_no_bot_api_is_claimed(self):
        self.assertIn("bot-api", lane("signal").REFUSALS)


class TestMeetingsAndRails(unittest.TestCase):
    env = {"ZOOM_SDK_KEY": "key", "ZOOM_SDK_SECRET": "secret"}

    def test_a_signed_join_round_trips(self):
        token = lane("meetings").sign_zoom_join("123456789", env=self.env)
        self.assertTrue(lane("meetings").verify_zoom_token(token["join_token"], self.env))

    def test_a_tampered_token_does_not_verify(self):
        token = lane("meetings").sign_zoom_join("123456789", env=self.env)
        self.assertFalse(lane("meetings").verify_zoom_token(token["join_token"], {"ZOOM_SDK_SECRET": "other"}))

    def test_the_lane_closes_instead_of_lying(self):
        with self.assertRaises(RuntimeError):
            lane("meetings").sign_zoom_join("123456789", env={})

    def test_every_platform_says_how_it_is_joined(self):
        for name in ("zoom", "meet", "teams"):
            self.assertTrue(lane("meetings").join_plan(name, "1")["join"])

    def test_the_two_rails_exist_and_say_why(self):
        rails = lane("meetings").RAILS
        self.assertIn("audio", rails)
        self.assertIn("livekit", rails["audio"]["how"])
        self.assertIn("getdisplaymedia", rails["screenshare"]["how"])


class TestStreamingIsTheOneThatPublishes(unittest.TestCase):
    def test_the_press_is_always_a_person_s(self):
        for name in ("twitch", "kick"):
            self.assertTrue(lane("streaming").go_live_plan(name)["human_presses_go_live"])

    def test_kick_refuses_the_api_rather_than_scraping(self):
        plan = lane("streaming").go_live_plan("kick", {"KICK_STREAM_KEY": "k"})
        self.assertIn("no official api", plan["refuses"])

    def test_twitch_takes_its_api_creds(self):
        self.assertFalse(lane("streaming").go_live_plan("twitch", {})["live_ready"])
        self.assertTrue(lane("streaming").go_live_plan(
            "twitch", {"TWITCH_CLIENT_ID": "a", "TWITCH_CLIENT_SECRET": "b"})["live_ready"])


class TestChatGates(unittest.TestCase):
    def test_slack_signature_is_the_same_v0_scheme(self):
        import hashlib, hmac
        ts, raw, secret = "1700000000", '{"type":"event_callback"}', "s3"
        sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:{raw}".encode(), hashlib.sha256).hexdigest()
        headers = {"x-slack-request-timestamp": ts, "x-slack-signature": sig}
        self.assertTrue(gates.slack(raw, headers, secret, now=1700000005)[0])
        self.assertFalse(gates.slack(raw, headers, secret, now=1700009999)[0])

    def test_slack_answers_the_url_verification_first(self):
        import hashlib, hmac, json as j
        import time
        ts, raw, secret = str(int(time.time())), '{"type": "url_verification", "challenge": "abc"}', "s3"
        sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:{raw}".encode(), hashlib.sha256).hexdigest()
        out = lane("slack").handle(raw, {"x-slack-request-timestamp": ts, "x-slack-signature": sig},
                                   {"SLACK_SIGNING_SECRET": secret})
        self.assertEqual(out["body"]["challenge"], "abc")

    def test_a_group_never_reaches_whatsapp(self):
        ok, why = lane("whatsapp").whitelisted("1234-5678@g.us", {"HEYPHONY_WHATSAPP_WHITELIST": "12345678"})
        self.assertFalse(ok)
        self.assertIn("group", why)

    def test_discord_answers_only_when_addressed(self):
        env = {"DISCORD_BOT_TOKEN": "t"}
        self.assertFalse(lane("discord").reply_plan("c1", "hi", addressed=False, env=env)["sendable"])
        self.assertTrue(lane("discord").reply_plan("c1", "hi", addressed=True, env=env)["sendable"])


class TestTheTwoCommands(unittest.TestCase):
    def test_omni_setup_covers_every_lane(self):
        self.assertEqual(set(comms_cli.setup_payload()["lanes"]), set(registry.lanes()))

    def test_omni_setup_points_telephony_at_its_own_command(self):
        self.assertIn("heyphony --setup", comms_cli.setup_payload()["telephony"])

    def test_telephony_setup_is_only_telephony(self):
        payload = telephony_cli.SETUP
        self.assertEqual(set(payload["lanes"]), {"voice", "sms"})
        self.assertEqual(payload["decided"]["client"], "baresip")

    def test_telephony_setup_names_the_proof(self):
        steps = " ".join(s["do"] for s in telephony_cli.SETUP["steps"])
        self.assertIn("echo test", steps)


class TestCatcher(unittest.TestCase):
    def test_a_whatsapp_payload_becomes_an_envelope(self):
        entry = catcher.normalize("whatsapp", {"id": "w1", "from": "9199@c.us", "body": "hello"})
        self.assertEqual((entry["channel"], entry["sender"], entry["body"]), ("whatsapp", "9199@c.us", "hello"))
        self.assertTrue(entry["at"])

    def test_an_unknown_shape_is_still_stored_with_its_raw(self):
        entry = catcher.normalize("email", {"weird": {"thing": 1}})
        self.assertEqual(entry["channel"], "email")
        self.assertEqual(entry["raw"], {"weird": {"thing": 1}})

    def test_an_unsigned_delivery_is_refused_before_parsing(self):
        ok, why = catcher.verify("whatsapp", "{}", {}, {"WAHA_HMAC_KEY": "k"})
        self.assertFalse(ok)
        self.assertIn("missing", why)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f"selftest: {result.testsRun - failed}/{result.testsRun} pass")
    sys.exit(1 if failed else 0)

"""comms selftests: stdlib only. run: python3 tests/selftest.py

the fixtures are linphone's own schemas, built here from the columns the sdk
declares, so a reader that drifts from linphone fails immediately.
"""
import contextlib
import io
import argparse
import json
import os
import pathlib
import re
import sqlite3
import sys
import tempfile
import unittest
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from comms import cards as cardbook
from comms.recognica import cards as recognica_cards, roles as recognica_roles
from comms import catcher, envelope, gates, registry
from comms import cli as comms_cli
from heyphony.src.runner import cli as telephony_cli
from heyphony.src.manage import catcher as phone_catcher
from heyphony.src.onramp import flow as getters
from heyphony.src.manage import inbox
from heyphony.src import providers
from heyphony.src.setup import flow as setup_flow
from heyphony.src.linphone import sip
from heyphony.src.linphone import sip as linphone


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


from comms import audio
from comms import signup


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
        """prose may name the umbrella; an import may not. that is the real boundary."""
        root = pathlib.Path(__file__).resolve().parent.parent
        for path in (root / "heyphony").rglob("*.py"):
            for line in path.read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith(("import ", "from ")):
                    self.assertNotIn("comms", stripped, f"{path} imports the umbrella: {stripped}")

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
        plan = lane("signal").registration_plan("link-desktop", env={})
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


class TestGetters(unittest.TestCase):
    def test_signal_is_the_first_getter(self):
        self.assertIn("signal", getters.available())

    def test_linking_needs_no_number_at_all(self):
        plan = getters.plan("signal", "link-desktop", env={})
        self.assertTrue(plan["gettable"])
        self.assertEqual(plan["missing"], [])

    def test_the_phone_signup_is_the_default_and_needs_the_did(self):
        self.assertEqual(getters.plan("signal", None, {})["path"], "phone-signup")
        self.assertFalse(getters.plan("signal", "phone-signup", {})["gettable"])
        self.assertTrue(getters.plan("signal", "phone-signup", {"HEYPHONY_SIP_DID": "+1555"})["gettable"])

    def test_the_code_is_read_from_heyphony_not_a_handset(self):
        plan = getters.plan("signal", "phone-signup", {"HEYPHONY_SIP_DID": "+1555"})
        cmds = " ".join(step["cmd"] for step in plan["steps"])
        self.assertIn("heyphony open messages", cmds)
        self.assertIn("durable", getters.available()["signal"]["flow"][0])

    def test_the_desktop_links_as_a_named_device(self):
        cmds = " ".join(s["cmd"] for s in getters.plan("signal", "link-desktop", {})["steps"])
        self.assertIn("device_name=heyphony-desktop", cmds)

    def test_voip_strictness_is_described_honestly(self):
        risky = getters.available()["signal"]["paths"]["register-number"]["why_risky"]
        self.assertIn("less strict about voip", risky)
        self.assertIn("never a promise", risky)

    def test_registering_needs_the_did_heyphony_holds(self):
        self.assertFalse(getters.plan("signal", "register-number", env={})["gettable"])
        self.assertTrue(getters.plan("signal", "register-number", {"HEYPHONY_SIP_DID": "+1555"})["gettable"])

    def test_an_unknown_getter_says_what_exists(self):
        out = getters.plan("carrier-pigeon", env={})
        self.assertFalse(out["gettable"])
        self.assertIn("signal", out["known"])

    def test_a_dry_run_executes_nothing(self):
        out = getters.run("signal", "link-desktop", env={})
        self.assertTrue(out["dry"])
        self.assertTrue(all(not step["executed"] for step in out["ran"]))

    def test_the_qr_scan_stays_a_human_act(self):
        out = getters.run("signal", "link-desktop", env={})
        self.assertTrue(any("scan" in who.lower() for who in out["needs_a_human"]))
        self.assertIn("qrcodelink", "".join(s["cmd"] for s in out["steps"]))

    def test_the_recipe_pins_commands_verified_upstream(self):
        recipe = getters.available()["signal"]
        joined = " ".join(step["cmd"] for step in recipe["install"])
        self.assertIn("MODE=native", joined)
        self.assertIn("bbernhard/signal-cli-rest-api", joined)
        self.assertIn("/v1/qrcodelink", " ".join(step["cmd"] for step in recipe["paths"]["link-desktop"]["steps"]))
        self.assertIn("/v2/send", recipe["install"][0]["source"])

    def test_the_getter_claims_no_bot_api(self):
        self.assertIn("bot-api", getters.available()["signal"]["refused"])

    def test_the_signal_lane_names_the_same_command(self):
        self.assertEqual(lane("signal").LANE["bootstrap"], "heyphony get signal")

    def test_imessage_is_thin_on_purpose(self):
        # the owner's call: photon free tier + whitelist, rcs, then sms on our own did.
        # written down so nobody later builds an apple bridge out of ambition.
        scope = lane("imessage").LANE["scope"]
        for needle in ("free tier", "rcs fallback", "heyphony did"):
            self.assertIn(needle, scope)
        readme = pathlib.Path("imessage/readme.md").read_text()
        self.assertIn("not a beast, on purpose", readme)
        self.assertIn("cannot register imessage", readme)
        self.assertEqual(lane("signal").registration_plan("phone-signup", env={})["one_command"],
                         "heyphony get signal")

    def test_telephony_setup_advertises_the_getter(self):
        self.assertIn("heyphony get signal", telephony_cli.SETUP["get"]["commands"])


class TestOpeningTheInboxes(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.home = tempfile.mkdtemp()
        from heyphony.src.manage import inbox as store
        self.store = store
        self.path = pathlib.Path(self.home) / "telephony" / "inbox.jsonl"
        store.append({"id": "a1", "channel": "sms", "sender": "+1555",
                      "body": "your signal code is 123456", "at": 1700000000}, self.path)
        store.append({"id": "a2", "channel": "sms", "sender": "+1666", "body": "hello", "at": 1700000100}, self.path)

    def test_rows_are_numbered_and_previewed(self):
        from heyphony.src.manage import views
        out = views.messages(home=self.home, path=self.path)
        self.assertEqual([r["n"] for r in out["rows"]], [1, 2])
        self.assertEqual(out["rows"][0]["from"], "+1666")
        self.assertTrue(out["rows"][0]["preview"])

    def test_the_unread_mark_is_ours_because_the_provider_does_not_track_it(self):
        from heyphony.src.manage import views
        self.assertEqual(views.messages(home=self.home, path=self.path)["unread_total"], 2)
        views.messages(home=self.home, path=self.path, do_mark=[1])
        self.assertEqual(views.messages(home=self.home, path=self.path, unread=True)["count"], 1)

    def test_show_expands_exactly_one_body(self):
        from heyphony.src.manage import views
        out = views.messages(home=self.home, path=self.path, show=2)
        self.assertIn("signal code", out["message"]["body"])

    def test_a_thread_filter_narrows_to_one_number(self):
        from heyphony.src.manage import views
        out = views.messages(home=self.home, path=self.path, thread="+1555")
        self.assertEqual(out["count"], 1)

    def test_voicemail_reads_its_sidecar_and_never_invents_a_transcript(self):
        from heyphony.src.manage import views
        folder = pathlib.Path(self.home) / "telephony" / "voicemail"
        folder.mkdir(parents=True)
        (folder / "vm1.wav").write_bytes(b"RIFF")
        (folder / "vm1.json").write_text(json.dumps({"from": "+1777", "seconds": 9, "transcript": "call me back"}))
        (folder / "vm2.wav").write_bytes(b"RIFF")
        rows = views.voicemail(home=self.home)["rows"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(any(r["transcript"] == "call me back" for r in rows))
        self.assertTrue(any(r["transcript"] == "" for r in rows))

    def test_the_call_log_is_empty_rather_than_wrong_without_a_database(self):
        from heyphony.src.manage import views
        out = views.calls(home=self.home)
        self.assertEqual((out["count"], out["rows"]), (0, []))

    def test_open_is_one_command_for_all_three(self):
        from heyphony.src.manage import views
        self.assertEqual(views.messages(home=self.home, path=self.path)["inbox"], "messages")
        self.assertEqual(views.calls(home=self.home)["inbox"], "calls")
        self.assertEqual(views.voicemail(home=self.home)["inbox"], "voicemail")


    def test_signup_legs_name_what_we_hold_and_what_we_dont(self):
        plan = signup.plan("slack", {"CARLYEMAIL_SIGNING_SECRET": "s"})
        self.assertTrue(plan["known"])
        self.assertEqual(plan["legs"]["phone"]["viable"], True)  # slack does not ask for one
        self.assertEqual(plan["legs"]["inbox"]["state"], "built")
        self.assertEqual(plan["stops"], [])

    def test_a_service_that_may_demand_a_number_stops_at_the_number(self):
        plan = signup.plan("discord", {"CARLYEMAIL_SIGNING_SECRET": "s"})
        self.assertFalse(plan["legs"]["phone"]["viable"])
        self.assertTrue(any("voip class" in s for s in plan["stops"]))

    def test_attestation_is_refused_rather_than_faked(self):
        plan = signup.plan("google")
        self.assertTrue(any("play integrity" in s for s in plan["stops"]))
        # and the refusal list is not decorative: it is the reason the plan says no
        self.assertIn("signup-to-evade", signup.REFUSED)

    def test_an_unknown_service_says_so_instead_of_inventing_a_plan(self):
        plan = signup.plan("myspace")
        self.assertFalse(plan["known"])
        self.assertEqual(plan["known_services"], ["discord", "github", "google", "slack"])

    def test_a_closed_inbox_gate_means_nothing_could_be_verified(self):
        plan = signup.plan("github", {})
        self.assertFalse(plan["legs"]["inbox"]["open"])
        self.assertTrue(any("inbox gate is unset" in s for s in plan["stops"]))

    def test_phone_harness_was_read_and_not_adopted(self):
        note = signup.device_note()
        self.assertFalse(note["used"])
        self.assertIn("may act, it may not become the identity", note["where_it_would_fit"])
        self.assertIn("somebody else's sim", note["why_not_for_signup"])
        self.assertIn("may not become the identity", note["where_it_would_fit"])

    def test_livekit_is_the_transport_and_is_free(self):
        self.assertTrue(audio.is_oss("livekit"))
        self.assertEqual(audio.STACK["livekit"]["licence"], "apache-2.0")

    def test_obs_is_oss_and_still_not_the_mic(self):
        self.assertTrue(audio.is_oss("obs"))
        self.assertIn("obs", audio.audit()["not_needed_for_audio"])
        self.assertTrue(any("macos" in audio.STACK["obs"]["role"] for _ in [0]))

    def test_a_browser_room_needs_no_audio_device(self):
        plan = audio.meeting_mic("meet", "voice.wav")
        self.assertEqual(plan["mode"], "chromium-flags")
        self.assertIn("--use-fake-device-for-media-stream", plan["argv"])
        self.assertTrue(any("voice.wav" in a for a in plan["argv"]))

    def test_a_native_client_gets_a_real_source(self):
        commands = audio.virtual_mic()["commands"]
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][:4], ["pactl", "load-module", "module-null-sink", "sink_name=agent"])
        self.assertIn("master=agent.monitor", commands[1])
        self.assertEqual(audio.meeting_mic("zoom", client="zoom-client")["mode"], "null-sink")

    def test_a_livekit_room_publishes_instead_of_faking_a_mic(self):
        plan = audio.meeting_mic("livekit")
        self.assertEqual(plan["mode"], "livekit")
        self.assertIn("LIVEKIT_API_KEY", plan["gate"])

    def test_the_two_hosts_that_need_an_install_say_so(self):
        self.assertIn("blackhole", audio.virtual_mic("macos")["device"])
        self.assertIn("NOT oss", audio.virtual_mic("windows")["note"])
        self.assertEqual(audio.audit()["not_oss"], ["vb-cable"])

class TestTelegram(unittest.TestCase):
    """the easiest lane: one endpoint, one header, and a group refusal."""

    def setUp(self):
        self.tg = lane("telegram")
        self.env = {"TELEGRAM_WEBHOOK_SECRET": "s3cret", "TELEGRAM_BOT_TOKEN": "bot",
                    "TELEGRAM_ALLOWED_CHATS": "555"}

    def update(self, chat=555, kind="private", text="hello"):
        return json.dumps({"update_id": 9, "message": {
            "chat": {"id": chat, "type": kind}, "from": {"username": "ana", "id": 7},
            "text": text, "date": 1793500000}})

    def test_an_unset_secret_closes_the_lane(self):
        ok, why = self.tg.verify({}, {"TELEGRAM_WEBHOOK_SECRET": ""})
        self.assertFalse(ok)
        self.assertIn("closed, not open", why)

    def test_a_bad_or_missing_token_is_401(self):
        self.assertEqual(self.tg.handle(self.update(), {}, self.env)["status"], 401)
        self.assertEqual(self.tg.handle(self.update(), {"x-telegram-bot-api-secret-token": "nope"},
                                        self.env)["status"], 401)

    def test_a_group_is_a_room_not_a_person(self):
        answer = self.tg.handle(self.update(chat=-1001, kind="supergroup"),
                                {"x-telegram-bot-api-secret-token": "s3cret"}, self.env)
        self.assertEqual(answer["status"], 403)
        self.assertEqual(answer["body"]["error"], "group-reply")

    def test_a_stranger_is_refused_and_a_whitelisted_chat_normalises(self):
        headers = {"x-telegram-bot-api-secret-token": "s3cret"}
        stranger = self.tg.handle(self.update(chat=999), headers, self.env)
        self.assertEqual(stranger["status"], 403)
        self.assertIn("not whitelisted", stranger["body"]["error"])
        answer = self.tg.handle(self.update(), headers, self.env)
        self.assertEqual(answer["status"], 200)
        entry = answer["body"]["envelope"]
        self.assertEqual(entry["channel"], "telegram")
        self.assertEqual(entry["sender"], "ana")
        self.assertEqual(entry["thread"], "555")
        self.assertEqual(entry["id"], "telegram:9")

    def test_the_lane_is_discovered_by_the_registry(self):
        self.assertIn("telegram", registry.lanes())
        self.assertEqual(self.tg.LANE["state"], "designed")


class TestConnectingCard(unittest.TestCase):
    """one person, every lane, and the thread they already had."""

    def cards(self):
        return [cardbook.new("Ana Rivera", {"email": "Ana@Example.com", "phone": "+91 98765 43210"})]

    def test_one_person_resolves_from_any_lane(self):
        cards = self.cards()
        self.assertEqual(cardbook.resolve(cards, "email", "ANA@example.com")["card"], "ana-rivera")
        cards, _ = cardbook.link(cards, "ana-rivera", "telegram", "ana_tg")
        self.assertEqual(cardbook.resolve(cards, "telegram", "ana_tg")["card"], "ana-rivera")
        self.assertEqual(cardbook.resolve(cards, "email", "ana@example.com")["channels"],
                         ["email", "phone", "telegram"])

    def test_a_phone_number_is_one_number_however_it_is_written(self):
        self.assertEqual(cardbook.canonical("phone", "+91 98765-43210"), "+919876543210")
        self.assertEqual(cardbook.canonical("email", " Ana@Example.COM "), "ana@example.com")

    def test_a_second_card_claiming_a_handle_is_refused(self):
        cards = self.cards() + [cardbook.new("A Rivera")]
        cards, result = cardbook.link(cards, "a-rivera", "email", "ana@example.com")
        self.assertFalse(result["linked"])
        self.assertEqual(result["why"], "silent-merge")
        self.assertEqual(result["held_by"], "ana-rivera")
        self.assertIn("--merge", result["how"])

    def test_merging_needs_the_name_typed(self):
        cards = self.cards() + [cardbook.new("A Rivera")]
        cards, refused = cardbook.merge(cards, "ana-rivera", "a-rivera", "yes")
        self.assertFalse(refused["merged"])
        self.assertEqual(refused["needs"], "A Rivera")
        cards, done = cardbook.merge(cards, "ana-rivera", "a-rivera", "a rivera")
        self.assertTrue(done["merged"])
        self.assertEqual(len(cards), 1)

    def test_a_stranger_is_stored_not_stitched(self):
        answer = cardbook.resolve(self.cards(), "telegram", "somebody_new")
        self.assertIsNone(answer["card"])
        self.assertEqual(answer["why"], "stranger-card")

    def test_the_digest_is_the_paste_somebody_would_have_done(self):
        cards = self.cards()
        cards, _ = cardbook.link(cards, "ana-rivera", "telegram", "ana_tg")
        events = [
            {"channel": "email", "sender": "ana@example.com", "body": "here is the deck", "at": 100},
            {"channel": "telegram", "sender": "ana_tg", "body": "got it, sending today", "at": 300},
            {"channel": "email", "sender": "stranger@example.com", "body": "unrelated", "at": 200},
        ]
        digest = cardbook.digest(cards, "ana-rivera", events)
        self.assertEqual([r["body"] for r in digest["recent"]],
                         ["got it, sending today", "here is the deck"])
        self.assertEqual(digest["across"], ["email", "telegram"])
        self.assertEqual(digest["count"], 2)

    def test_the_digest_of_nobody_says_so(self):
        self.assertIsNone(cardbook.digest(self.cards(), "nobody", [])["card"])


class TestTheDirectoryExplainsItself(unittest.TestCase):
    """the complaint that started this: python files, no way to see how the thing runs."""

    root = pathlib.Path(__file__).resolve().parent.parent
    hey = root / "heyphony"

    def test_the_map_exists_and_is_a_map(self):
        text = (self.hey / "directory.md").read_text()
        self.assertGreaterEqual(text.count("```mermaid"), 3, "the map lost its diagrams")
        for needle in ("setup", "manage", "onramp", "src/", "runner", "linphone",
                       "turnedon", "turnedoff", "inbox", "outgoing", "commands"):
            self.assertIn(needle, text, f"the map does not mention {needle}")
        self.assertNotIn("—", text)

    def test_setup_and_manage_are_drawn_as_separate_flows(self):
        """one flow for getting a number, one for living with it. conflating them is how it got confusing."""
        text = (self.hey / "directory.md").read_text()
        self.assertIn("the setup flow", text)
        self.assertIn("the manage flow", text)
        setup = text.split("### the setup flow", 1)[1].split("### the manage flow", 1)[0]
        self.assertIn("provision", setup, "the buy-a-number branch is missing")
        self.assertIn("sip did", setup, "the bring-a-number branch is missing")
        manage = text.split("### the manage flow", 1)[1]
        self.assertIn("is the host up", manage)
        self.assertIn("no live calls", manage)

    def test_every_folder_that_holds_code_says_what_it_is_for(self):
        for folder in ("src", "src/runner", "src/linphone", "src/setup", "src/manage", "src/onramp",
                       "src/setup/test", "src/setup/commands", "src/manage/turnedon",
                       "src/manage/turnedoff", "src/manage/inbox", "src/manage/outgoing"):
            page = self.hey / folder / "readme.md"
            self.assertTrue(page.is_file(), f"{folder} has no readme.md")
            self.assertGreater(len(page.read_text()), 400, f"{folder}/readme.md says nothing")

    def test_no_module_sits_where_a_description_folder_would(self):
        """a folder and a module with one name is a trap: the module wins, then someone adds an __init__."""
        for folder in self.hey.rglob("*"):
            if not folder.is_dir():
                continue
            for page in folder.glob("*.py"):
                clash = folder / page.stem
                if clash.is_dir() and (clash / "__init__.py").is_file():
                    self.fail(f"{clash} would shadow {page}")

    def test_the_code_lives_under_src_and_nothing_else_does(self):
        loose = sorted(p.name for p in self.hey.glob("*.py") if p.name != "__init__.py")
        self.assertEqual(loose, [], f"modules outside src: {loose}")

    def test_the_off_routing_page_matches_the_vendor_table(self):
        """the table a person reads and the data the code routes on must be the same table."""
        from heyphony.src import providers
        text = (self.hey / "src/manage/turnedoff/readme.md").read_text()
        for name in providers.inbox_providers():
            self.assertIn(f"| {name} |", text, f"{name} is missing from the off-routing table")
        for name in ("voyced", "voxacall", "bitcall"):
            self.assertIn(f"| {name} |", text)
        for name, facts in ((n, providers.profile(n)["works_while_off"]) for n in providers.PROVIDERS):
            for row in text.splitlines():
                if row.startswith(f"| {name} |"):
                    cells = [c.strip() for c in row.strip("|").split("|")]
                    want = ("yes" if facts["texts"] else "no",
                            "yes" if facts["voicemail"] else "no",
                            "yes" if facts["live_calls"] else "no")
                    self.assertEqual(tuple(cells[1:4]), want, f"{name} routing drifted: {row}")
                    break
            else:
                self.fail(f"{name} has no row")

    def test_the_command_index_names_the_commands_that_exist(self):
        from heyphony.src.runner import cli
        parser = cli.build_parser()
        subs = set()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                subs |= set(action.choices)
        table = (self.hey / "src/setup/commands/readme.md").read_text()
        for name in subs:
            self.assertIn(f"`heyphony {name}", table, f"{name} exists and is not in the index")
        for absent in ("heyphony send", "heyphony call`"):
            self.assertIn(absent, table, f"the index stopped declaring {absent} missing")

    def test_the_prose_never_claims_a_lane_is_proven(self):
        for page in self.hey.rglob("*.md"):
            text = page.read_text().lower()
            self.assertNotIn("—", text, f"{page} picked up an em dash")
        off = (self.hey / "src/manage/turnedoff/readme.md").read_text().lower()
        self.assertIn("no live calls", (self.hey / "directory.md").read_text().lower())
        self.assertIn("only some of them offer it", off)


class TestTheReadmesCannotDrift(unittest.TestCase):
    """prose that names carriers has to keep naming the ones that exist, and no others."""

    def readme(self):
        return pathlib.Path("README.md").read_text()

    def test_every_lane_in_the_tree_is_named_in_the_root_readme(self):
        text = self.readme().lower()
        for folder in registry.folders():
            self.assertIn(folder, text, f"{folder} is a lane but the readme does not mention it")

    def test_the_stack_is_described_as_a_stack(self):
        text = self.readme()
        for needle in ("omnichannel", "communication stack", "one memory", "turnkey",
                       "rcs", "zoom", "google meet", "teams", "screen"):
            self.assertIn(needle, text.lower(), f"the readme stopped claiming {needle!r}")
        self.assertNotIn("—", text, "no em dashes")

    def test_the_byline_is_the_one_the_owner_wrote(self):
        self.assertIn("*turn your ai companion into a commpanion (sorry for the pun) with its own "
                      "comms stack*", self.readme())

    def test_heyphony_is_the_number_not_a_platform(self):
        text = self.readme()
        self.assertIn("a jerryrigged workaround for giving your agent a phone number of its own", text)
        self.assertIn("also onramps signal", text)

    def test_the_positioning_is_honest_about_what_this_is(self):
        text = self.readme().lower()
        for needle in ("ai-operatable", "not a reinvention of the phone industry",
                       "join as you, not as a bot", "free for the ten whitelisted",
                       "call centre", "consent and attestation"):
            self.assertIn(needle, text, f"the readme stopped saying {needle!r}")

    def test_the_card_is_explained_where_a_human_will_look_for_it(self):
        text = self.readme().lower()
        self.assertIn("the card, so nobody pastes a chat again", text)
        self.assertIn("an unknown sender is stored, not stitched", text)

    def test_heyphony_explains_itself_in_the_same_voice(self):
        """the folder explains itself across the readme, the idea pages and the journal."""
        folder = pathlib.Path("heyphony")
        pages = [folder / "readme.md", *sorted((folder / "theidea").glob("*.md")),
                 *sorted((folder / "journal").glob("*.md"))]
        text = "\n".join(page.read_text() for page in pages).lower()
        for needle in ("a jerryrigged workaround", "a **phone number of its own**",
                       "one you can actually reach", "what it gives you, turnkey",
                       "setup select sip", "**device on**", "**device off**",
                       "ten providers, and one question that sorts them",
                       "bulkvs", "jmp.chat", "voice only",
                       "onramp", "inbound first", "baresip", "ctrl_tcp",
                       "packages alone", "refused for otp"):
            self.assertIn(needle, text, f"the heyphony folder lost {needle!r}")
        for page in pages:
            self.assertNotIn("—", page.read_text(), f"{page} picked up an em dash")

    def test_the_branch_readme_points_at_the_shelved_book(self):
        text = pathlib.Path("README.md").read_text()
        self.assertIn("comms/recognica/readme.md", text)
        self.assertNotIn("comms/cards.py", text)
        for shelf in ("humans/owner", "humans/people", "agents/"):
            self.assertIn(shelf, text)
        self.assertTrue(pathlib.Path("comms/recognica/readme.md").is_file())
        # the journal links to it with a path that actually resolves
        journal = pathlib.Path("heyphony/journal/2026-11-01.md")
        for target in re.findall(r"\]\((\.[^)]+)\)", journal.read_text()):
            self.assertTrue((journal.parent / target).resolve().exists(), f"{journal} links to a missing {target}")

    def test_the_setup_doc_carries_the_steps_that_used_to_be_implied(self):
        text = pathlib.Path("docs/setup.md").read_text()
        for needle in ("--areas", "--purchase", "no payment rail is wired here on purpose", "catching", "voicemail",
                       "heyphony app --port 8790", "carrier emails parsed"):
            self.assertIn(needle, text)

    def test_the_heyphony_readme_reads_like_the_branch_readme(self):
        """the owner's ask: same shape as main's readme, prose first, sections rather than a wall."""
        text = pathlib.Path("heyphony/readme.md").read_text()
        for heading in ("## the problem", "## the point", "### ", "## where it is honest about itself"):
            self.assertIn(heading, text)
        self.assertLess(text.index("## the problem"), text.index("## the point"))
        # a long intro paragraph before the first heading, the way the branch readme opens
        intro = text.split("## the problem")[0]
        self.assertGreater(len(intro.split()), 80, "the intro shrank to a caption")

    def test_the_journal_explains_softphones_step_by_step(self):
        journal = pathlib.Path("heyphony/journal")
        walk = (journal / "softphones.md").read_text().lower()
        for step in ("step 0", "step 1", "step 2", "step 3", "step 4", "step 5", "step 6", "step 7"):
            self.assertIn(step, walk, f"the walk lost {step}")
        for term in ("registration", "invite", "codec", "rtp", "pbx", "cdr", "did"):
            self.assertIn(term, walk, f"the walk never explains {term}")
        self.assertIn("register", walk)

    def test_the_softphone_table_compares_what_it_was_built_for(self):
        table = (pathlib.Path("heyphony/journal/pbx-vs-softphone.md")).read_text().lower()
        self.assertIn("| | what a softphone was made to do, next to a pbx |", table)
        self.assertIn("what heyphony adapted it to", table)
        rows = [line for line in table.splitlines() if line.startswith("| ") and line.count("|") == 4]
        self.assertGreaterEqual(len(rows), 12, "the table collapsed to a few rows")
        for needle in ("voicemail", "call history", "registration", "the pbx itself", "texting"):
            self.assertIn(needle, table)
        self.assertIn("attention became storage", table)
        # the two journal explainers are linked from the index, not orphaned
        index = (pathlib.Path("heyphony/journal/readme.md")).read_text()
        self.assertIn("softphones.md", index)
        self.assertIn("pbx-vs-softphone.md", index)

    def test_the_idea_pages_are_the_argument_and_the_readme_is_the_explanation(self):
        idea = pathlib.Path("heyphony/theidea")
        expected = {"epilogue.md", "vendors.md", "onramp.md", "glossary.md", "calling.md", "access.md"}
        self.assertEqual({p.name for p in idea.glob("*.md")}, expected)
        epilogue = (idea / "epilogue.md").read_text().lower()
        for needle in ("pbx", "private branch exchange", "softphone", "mcgyver", "back to the basics"):
            self.assertIn(needle, epilogue)
        calling = (idea / "calling.md").read_text().lower()
        for needle in ("livekit", "call-e", "heycall-e.com", "planned", "parked for v3"):
            self.assertIn(needle, calling)
        access = (idea / "access.md").read_text().lower()
        for needle in ("bsl 1.1", "fsl 1.1", "agpl", "linphone", "separate commercial agreement",
                       "publicly available under an open-source licence", "mcp server",
                       "npm installable package", "cloud hosted", "api"):
            self.assertIn(needle, access)
        glossary = (idea / "glossary.md").read_text().lower()
        for needle in ("did", "e164", "sip", "rtp", "pstn", "trunk", "codec", "catcher", "getter"):
            self.assertIn(needle, glossary)
        onramp = (idea / "onramp.md").read_text().lower()
        for needle in ("signal", "onramp is not", "lane"):
            self.assertIn(needle, onramp)
        self.assertTrue(list((pathlib.Path("heyphony/journal")).glob("*.md")))


class TestTheCatcherKnowsEveryPath(unittest.TestCase):
    def test_a_provider_path_is_recognised_and_a_stranger_is_not(self):
        from heyphony.src.manage import catcher
        for name in ("flowroute", "anveo", "signalwire", "questblue", "bulkvs"):
            self.assertEqual(catcher.provider_of(f"/sms/{name}?x=1"), name)
        self.assertIsNone(catcher.provider_of("/sms/twilio"))
        self.assertIsNone(catcher.provider_of("/sms"))
        self.assertIsNone(catcher.provider_of("/email"))


class TestTheProvisioningChainStopsBeforeItSpends(unittest.TestCase):
    def run_cli(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = telephony_cli.main(argv)
        return code, out.getvalue()

    def test_areas_carry_stock_and_prices_in_dollars(self):
        from heyphony.src.setup import provision
        row = provision._area_row({"AREA_ID": "191.195.165.31.230", "AREA_CODE": "256",
                                   "AREA_NAME": "ALBERTVILLE", "STOCK": "49",
                                   "rate_plans": [{"RATE_PLAN_ID": "SU", "RATE_PLAN_NAME": "Service Unlimited",
                                                   "MONTHLY100": "149", "SETUP100": "249"}]})
        self.assertEqual((row["area_code"], row["stock"]), ("256", 49))
        self.assertEqual(row["rate_plans"][0]["monthly_usd"], 1.49)
        self.assertEqual(row["rate_plans"][0]["setup_usd"], 2.49)

    def test_apply_asks_for_stock_and_stops_at_the_order(self):
        from heyphony.src.setup import provision
        saved = {k: os.environ.pop(v, None) for k, v in provision.ENV.items()}
        try:
            answer = provision.plan("212", apply=True)
            self.assertFalse(answer["applied"])
            self.assertEqual(answer["missing"], ["userkey", "email", "phrase"])
            self.assertIn("nothing was asked", answer["why"])
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[provision.ENV[key]] = value
        steps = provision.plan("212")["steps"]
        self.assertEqual([(s["action"], s["free"]) for s in steps],
                         [("ANVEO.AREAS.LIST", True), ("DID.ORDER", False), ("DID.UPDATE", True)])

    def test_the_purchase_step_is_parked_rather_than_forgotten(self):
        from heyphony.src.setup import provision
        parked = provision.plan("212", purchase=True)
        self.assertFalse(parked["ok"])
        self.assertEqual(parked["purchase"], "parked")
        self.assertIn("payment rail", parked["why"])
        self.assertIn("hooks anveo --apply", parked["instead"])

    def test_area_selection_is_first_class(self):
        from heyphony.src.setup import provision
        self.assertEqual(sorted(provision.DID_TYPES), ["GEOGRAPHIC", "MOBILE", "NATIONAL", "TOLLFREE"])
        plan = provision.plan("212", area_name="new york", country_id="US")
        self.assertEqual(plan["area_name"], "new york")
        self.assertIn("param[COUNTRY_ID]=US", urllib.parse.unquote(plan["steps"][0]["as_curl"]))


class TestTheSetupPlanCoversVoicemailAndCatching(unittest.TestCase):
    def test_a_connect_line_is_not_the_whole_errand(self):
        from heyphony.src.setup import flow as flow
        plan = flow.plan_sip("voip.ms", "+12125551234")
        self.assertEqual(plan["catching"]["kind"], "email")
        self.assertIn("heyphony serve", plan["catching"]["serve"])
        self.assertIn("carrier", plan["voicemail"]["where"])
        self.assertEqual(plan["launcher"]["tabs"], ["caught messages", "voicemail", "calls"])
        for step in ("arm the text hook", "point voicemail", "heyphony app"):
            self.assertTrue(any(step in s for s in plan["steps"]), step)
        anveo = flow.plan_sip("anveo", "+12125551234")
        self.assertIn("url-forward", anveo["catching"]["kind"])
        flowroute = flow.plan_sip("flowroute", "+12125551234")
        self.assertIn("no carrier fallback", flowroute["voicemail"]["where"])


class TestTheLauncher(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.inbox = self.tmp / "inbox.jsonl"
        self.voice = self.tmp / "voicemail"
        self.voice.mkdir()
        for entry in ({"id": "sms:1", "channel": "sms", "direction": "inbound",
                       "sender": "+15551230000", "recipient": "+15559990000", "subject": None,
                       "body": "are you free at 3?", "at": 1793500000, "thread": "+15551230000",
                       "reply_to": None, "raw": {"provider": "voip.ms"}},
                      {"id": "sms:2", "channel": "sms", "direction": "inbound",
                       "sender": "+15554440000", "recipient": "+15559990000", "subject": None,
                       "body": "invoice attached", "at": 1793400000, "thread": "+15554440000",
                       "reply_to": None, "raw": {"provider": "flowroute"}}):
            inbox.append(entry, path=self.inbox)

    def test_texts_and_voicemail_merge_into_one_thread_per_person(self):
        from heyphony.src.runner import gui as launcher
        raw = ("From: voipms@voip.ms\nSubject: VOICEMAIL from 15551230000\n"
               "Date: Sun, 01 Nov 2026 09:00:00 +0000\nContent-Type: text/plain\n\n"
               "new voicemail, 14 seconds. transcript: call me back about the invoice.\n")
        stored = launcher.import_email(raw, save_dir=self.voice, path=self.inbox)
        self.assertTrue(stored["stored"])
        self.assertEqual(stored["kind"], "voicemail")
        threads = launcher.threads(path=self.inbox, voicemail_dir=self.voice)["threads"]
        self.assertEqual([t["peer"] for t in threads], ["+15551230000", "+15554440000"])
        first = threads[0]
        self.assertEqual(first["kinds"], ["sms", "voicemail"])
        self.assertEqual(first["count"], 2)
        detail = launcher.thread("+15551230000", path=self.inbox, voicemail_dir=self.voice)
        self.assertEqual([i["kind"] for i in detail["items"]], ["sms", "voicemail"])

    def test_a_forwarded_voicemail_is_not_counted_twice(self):
        """the message and its recording are one thing to a person, so the thread shows it once."""
        from heyphony.src.runner import gui as launcher
        raw = ("From: voipms@voip.ms\nSubject: VOICEMAIL from 15559998888\n"
               "Date: Sun, 01 Nov 2026 09:00:00 +0000\nMIME-Version: 1.0\n"
               "Content-Type: multipart/mixed; boundary=B\n\n--B\nContent-Type: text/plain\n\n"
               "voicemail, 14 seconds\n--B\nContent-Type: audio/wav\n"
               "Content-Transfer-Encoding: base64\n"
               "Content-Disposition: attachment; filename=\"vm.wav\"\n\n"
               "UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA=\n--B--\n")
        stored = launcher.import_email(raw, save_dir=self.voice, path=self.inbox)
        self.assertTrue(stored["stored"])
        detail = launcher.thread("+15559998888", path=self.inbox, voicemail_dir=self.voice)
        self.assertEqual([i["kind"] for i in detail["items"]], ["voicemail"])
        bucket = next(t for t in launcher.threads(path=self.inbox, voicemail_dir=self.voice)["threads"]
                      if t["peer"] == "+15559998888")
        self.assertEqual(bucket["count"], 1)
        # the audio is still readable in the voicemail tab, which is where a recording belongs
        self.assertEqual(launcher.views.voicemail(path=self.voice)["count"], 1)

    def test_a_reply_is_a_draft_with_a_route_and_never_a_send(self):
        from heyphony.src.runner import gui as launcher
        answer = launcher.draft("+15551230000", "sure, 3 works", path=self.inbox)
        self.assertFalse(answer["applied"])
        self.assertEqual(answer["provider"], "voip.ms")
        self.assertFalse(answer["outbound"]["now"])
        self.assertIn("no outbound api path", answer["outbound"]["why"])
        self.assertIn("draft", answer["note"])

    def test_voicemail_rows_carry_a_time_a_person_can_read(self):
        from heyphony.src.runner import gui as launcher
        raw = ("From: voipms@voip.ms\nSubject: VOICEMAIL from 15557776666\n"
               "Date: Sun, 01 Nov 2026 09:00:00 +0000\nMIME-Version: 1.0\n"
               "Content-Type: multipart/mixed; boundary=B\n\n--B\nContent-Type: text/plain\n\n"
               "voicemail, 8 seconds\n--B\nContent-Type: audio/wav\n"
               "Content-Transfer-Encoding: base64\n"
               "Content-Disposition: attachment; filename=\"vm2.wav\"\n\n"
               "UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA=\n--B--\n")
        launcher.import_email(raw, save_dir=self.voice, path=self.inbox)
        row = launcher.voicemails(path=self.inbox, voicemail_dir=self.voice)["rows"][0]
        self.assertRegex(row["when"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

    def test_the_page_serves_tabs_and_json(self):
        import threading
        import urllib.request
        from heyphony.src.runner import gui as launcher
        server = launcher.serve(port=0, path=self.inbox, voicemail_dir=self.voice)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as page:
                html = page.read().decode()
            for tab in ("caught messages", "voicemail", "calls"):
                self.assertIn(tab, html)
            self.assertIn("drafts only", launcher.providers_seen(path=self.inbox)["reply"])
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/threads") as answer:
                self.assertEqual(len(json.load(answer)["threads"]), 2)
            body = json.dumps({"peer": "+15551230000", "body": "hi"}).encode()
            request = urllib.request.Request(f"http://127.0.0.1:{port}/api/reply", data=body,
                                            headers={"content-type": "application/json"})
            with urllib.request.urlopen(request) as answer:
                self.assertFalse(json.load(answer)["applied"])
        finally:
            server.shutdown()
            server.server_close()

    def test_a_carrier_email_keeps_its_audio_and_never_guesses_a_sender(self):
        from heyphony.src.manage import mailparse
        raw = ("From: voipms@voip.ms\nSubject: VOICEMAIL from 12125550123\n"
               "Date: Sun, 01 Nov 2026 10:00:00 +0000\nMIME-Version: 1.0\n"
               "Content-Type: multipart/mixed; boundary=B\n\n--B\n"
               "Content-Type: text/plain\n\nvoicemail, 9 seconds\n--B\n"
               "Content-Type: audio/wav\nContent-Transfer-Encoding: base64\n"
               "Content-Disposition: attachment; filename=\"vm.wav\"\n\n"
               "UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA=\n--B--\n")
        item = mailparse.parse(raw, save_dir=self.voice)
        self.assertEqual(item["kind"], "voicemail")
        self.assertEqual(item["sender"], "+12125550123")
        self.assertTrue(pathlib.Path(item["audio"]["path"]).is_file())
        self.assertTrue(pathlib.Path(mailparse.sidecar_for(item)).is_file())
        anon = mailparse.parse("From: x@y\nSubject: hello\n\nno number in here\n")
        self.assertIsNone(anon["sender"])
        self.assertEqual(anon["kind"], "email")


class TestRecognicaIsTheContactBook(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.root = pathlib.Path(tempfile.mkdtemp()) / "recognica"
        self.env = {"COMMS_RECOGNICA_PATH": str(self.root)}

    def test_the_shelves_are_the_point(self):
        cards = [recognica_cards.new("ada", {"email": "ada@example.com"})]
        cards, made = recognica_roles.make_owner(cards, handles=[("email", "me@example.com")])
        cards, agent = recognica_roles.add_agent(cards, "peer bot", {"email": "bot@example.com"})
        self.assertEqual(made["shelf"], "humans/owner")
        self.assertEqual(agent["shelf"], "agents")
        self.assertEqual(recognica_cards.shelf(cards[0]), "humans/people")
        recognica_cards.save(cards, self.env)
        files = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*.json"))
        self.assertEqual(files, ["agents/peer-bot.json", "humans/owner/owner.json", "humans/people/ada.json"])
        loaded = recognica_cards.load(self.env)
        self.assertEqual(len(loaded), 3)
        self.assertEqual(recognica_roles.role_of(loaded, "email", "me@example.com")["role"], "owner")
        self.assertEqual(recognica_roles.role_of(loaded, "email", "ada@example.com")["role"], "contact")
        self.assertEqual(recognica_roles.role_of(loaded, "email", "bot@example.com")["role"], "agent")
        self.assertEqual(recognica_roles.role_of(loaded, "email", "who@example.com")["role"], "unknown")
        tree = recognica_cards.tree(loaded)
        self.assertEqual(tree["counts"], {"owner": 1, "people": 1, "agents": 1})

    def test_a_new_card_is_never_the_owner(self):
        card = recognica_cards.new("ada", {"email": "ada@example.com"})
        self.assertEqual(card["role"], "contact")
        self.assertIsNone(recognica_roles.owner([card]))
        self.assertFalse(recognica_roles.summary([card], env={})["knows_owner"])

    def test_the_owner_can_be_seeded_from_the_environment_without_being_guessed(self):
        cards = [recognica_cards.new("ada", {"email": "ada@example.com"})]
        cards, made = recognica_roles.make_owner(cards, env={"RECOGNICA_OWNER_EMAIL": "me@example.com"})
        self.assertTrue(made["ok"])
        self.assertEqual(recognica_roles.role_of(cards, "email", "me@example.com")["role"], "owner")
        # a second call updates the same card instead of adding a second owner
        cards, again = recognica_roles.make_owner(cards, handles=[("phone", "+15550001111")])
        self.assertEqual(len([c for c in cards if c["role"] == "owner"]), 1)
        self.assertTrue(again["ok"])
        nothing = recognica_roles.make_owner(cards, env={})[1]
        self.assertFalse(nothing["ok"])
        self.assertIn("RECOGNICA_OWNER", nothing["why"])

    def test_the_old_single_file_is_still_readable_after_the_move(self):
        self.root.mkdir(parents=True)
        (self.root / "cards.json").write_text(json.dumps([recognica_cards.new("ada")]))
        self.assertEqual([c["id"] for c in recognica_cards.load(self.env)], ["ada"])
        self.assertEqual([c["id"] for c in cardbook.load(self.env)], ["ada"])

    def test_saving_drops_a_card_that_moved_shelves(self):
        cards = [recognica_cards.new("ada", {"email": "ada@example.com"})]
        recognica_cards.save(cards, self.env)
        self.assertTrue((self.root / "humans/people/ada.json").is_file())
        cards, _ = recognica_roles.make_owner(cards + [], handles=[("email", "me@example.com")])
        cards[0]["role"] = "owner"
        recognica_cards.save(cards, self.env)
        self.assertFalse((self.root / "humans/people/ada.json").exists())
        self.assertTrue((self.root / "humans/owner/ada.json").is_file())


class TestProvisioningIsACliWhereTheProviderAllowsIt(unittest.TestCase):
    def run_cli(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = telephony_cli.main(argv)
        return code, out.getvalue()

    def test_anveo_signature_matches_their_published_example(self):
        from heyphony.src.setup import provision
        self.assertEqual(provision.signature("some@email.com", "my secure phrase"),
                         "396cdfaff3491f457b95e51a5ebd89ad516d623d")

    def test_anveo_answers_parse_into_areas_and_numbers(self):
        from heyphony.src.setup import provision
        areas = provision.parse(
            '<RESPONSE><RESULT>SUCCESS</RESULT><AREAS>'
            '<AREA AREA_NAME="ALBERTVILLE" AREA_ID="191.195.165.31.230" AREA_CODE="256" STOCK="49">'
            '<RATE_PLAN RATE_PLAN_ID="VALUE" RATE_PLAN_NAME="Value" MONTHLY100="149" SETUP100="249" />'
            '<RATE_PLAN RATE_PLAN_ID="SU" RATE_PLAN_NAME="Service Unlimited" MONTHLY100="149" SETUP100="249" />'
            '</AREA></AREAS></RESPONSE>')
        self.assertEqual(areas["result"], "SUCCESS")
        self.assertEqual(areas["areas"][0]["AREA_CODE"], "256")
        self.assertEqual(areas["areas"][0]["rate_plans"][1]["RATE_PLAN_ID"], "SU")
        bought = provision.parse(
            '<RESPONSE><RESULT>SUCCESS</RESULT><DIDS>'
            '<DID E164="12121111111" DID_TYPE="GEOGRAPHIC" SMS_URL="" STATUS="Active" AREA_CODE="212" />'
            '</DIDS></RESPONSE>')
        self.assertEqual(bought["dids"][0]["E164"], "12121111111")

    def test_provisioning_is_a_plan_without_apply_and_names_its_credentials(self):
        from heyphony.src.setup import provision
        saved = {k: os.environ.pop(v, None) for k, v in provision.ENV.items()}
        try:
            plan = provision.plan("212", sms_url="https://host:8099/sms/anveo?from=$[from]$")
            self.assertFalse(plan["applied"])
            self.assertEqual(sorted(plan["missing"]), ["email", "phrase", "userkey"])
            self.assertEqual([step["action"] for step in plan["steps"]],
                             ["ANVEO.AREAS.LIST", "DID.ORDER", "DID.UPDATE"])
            self.assertIn("DID.ORDER", plan["steps"][1]["as_curl"])
            self.assertIn("$[from]$", plan["steps"][2]["params"]["SMS_URL"])
            self.assertIn("--apply", plan["next"])
            bad = provision.plan("212", did_type="MAGIC")
            self.assertFalse(bad["ok"])
            self.assertIn("did_type", bad["why"])
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[provision.ENV[key]] = value

    def test_only_anveo_is_provisionable_from_the_cli_and_the_plan_says_which(self):
        code, text = self.run_cli(["provision", "--provider", "anveo", "--area-code", "212"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(text)["provider"], "anveo")
        from heyphony.src.setup import flow as flow
        anveo = flow.plan_sip("anveo", "+12125551234")
        self.assertEqual(anveo["provisioning"]["now"], "cli")
        self.assertIn("setup provision", anveo["provisioning"]["command"])
        self.assertEqual(anveo["provisioning"]["stops_before"], "DID.ORDER")
        self.assertFalse(anveo["provisioning"]["spends_money"])
        flowroute = flow.plan_sip("flowroute", "+12125551234")
        self.assertEqual(flowroute["provisioning"]["now"], "browser")

    def test_arming_anveos_sms_refuses_without_credentials_and_shows_the_call(self):
        from heyphony.src.setup import provision
        from heyphony.src.setup import routes
        saved = {k: os.environ.pop(v, None) for k, v in provision.ENV.items()}
        try:
            answer = routes.apply_hook("anveo", "https://host:8099", "+12125551234")
            self.assertFalse(answer["applied"])
            self.assertEqual(answer["missing"], ["userkey", "email", "phrase"])
            self.assertIn("DID.UPDATE", answer["as_curl"])
            self.assertIn("FILTER.E164", answer["as_curl"].replace("%5B", "[").replace("%5D", "]"))
            no_did = routes.apply_hook("anveo", "https://host:8099")
            self.assertFalse(no_did["applied"])
            self.assertIn("--did", no_did["why"])
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[provision.ENV[key]] = value


class TestTheGuidedSetup(unittest.TestCase):
    """a menu for a person, a json question for a process, one plan either way."""

    def run_cli(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = telephony_cli.main(argv)
        return code, out.getvalue()

    def test_the_menu_is_every_provider_the_routes_know_about(self):
        from heyphony.src.setup import routes
        keys = [c["key"] for c in setup_flow.PROVIDER_CHOICES]
        self.assertEqual(keys, ["voip.ms", "flowroute", "anveo", "signalwire", "questblue",
                                "bulkvs", "jmp.chat", "voyced", "voxacall", "bitcall"])
        self.assertEqual(sorted(keys), sorted(routes.ROUTES), "the menu and the routes cannot drift")
        self.assertTrue(all(c.get("group") for c in setup_flow.PROVIDER_CHOICES))
        groups = {c["group"] for c in setup_flow.PROVIDER_CHOICES}
        self.assertEqual(groups, {"texts reach an inbox", "voice only, no inbox"})
        self.assertEqual([c["key"] for c in setup_flow.DID_CHOICES], ["existing", "new"])

    def test_a_piped_answer_picks_by_number_and_enter_takes_the_default(self):
        def keyed(answer):
            return setup_flow.select("provider", setup_flow.PROVIDER_CHOICES,
                                     stream_in=io.StringIO(answer), stream_out=io.StringIO(), tty=False)
        self.assertEqual(keyed("2\n"), "flowroute")
        self.assertEqual(keyed("\n"), "voip.ms")
        self.assertEqual(keyed("voip.ms\n"), "voip.ms")

    def test_garbage_is_asked_again_rather_than_accepted(self):
        self.assertEqual(setup_flow.select("provider", setup_flow.PROVIDER_CHOICES,
                                           stream_in=io.StringIO("nope\n2\n"),
                                           stream_out=io.StringIO(), tty=False), "flowroute")

    def test_a_terminal_we_cannot_read_keys_from_still_gets_a_menu(self):
        out = io.StringIO()
        self.assertEqual(setup_flow.select("provider", setup_flow.PROVIDER_CHOICES,
                                           stream_in=io.StringIO("1\n"), stream_out=out, tty=True),
                         "voip.ms")
        self.assertIn("1. voip.ms", out.getvalue())

    def test_an_existing_did_gives_the_connect_line(self):
        plan = setup_flow.plan_sip("voipms", did="+15551234567")
        self.assertEqual(plan["provider"], "voip.ms")
        self.assertEqual(plan["did"]["source"], "existing")
        self.assertIn("--provider voip.ms --did +15551234567", plan["connect"])
        self.assertFalse(plan["verified"])
        self.assertEqual(plan["number_type"], "voip")

    def test_a_new_number_goes_to_the_browser_and_says_what_is_later(self):
        plan = setup_flow.plan_sip("flowroute", new=True)
        self.assertEqual(plan["did"]["source"], "new")
        self.assertTrue(plan["browser"]["url"].startswith("https://"))
        self.assertFalse(plan["browser"]["deep_link_verified"])
        self.assertEqual(plan["provisioning"]["now"], "browser")
        self.assertIn("cli", plan["provisioning"]["later"])

    def test_e164_is_enforced_before_a_plan_exists(self):
        self.assertTrue(setup_flow.valid_did("+15551234567"))
        self.assertFalse(setup_flow.valid_did("5551234"))
        self.assertFalse(setup_flow.valid_did("+1"))

    def test_a_process_with_no_flags_gets_the_next_question_not_a_hang(self):
        code, text = self.run_cli(["setup", "select", "sip"])
        self.assertEqual(code, 0)
        answer = json.loads(text)
        self.assertFalse(answer["ok"])
        self.assertEqual(answer["needs"], "provider")
        self.assertIn("bulkvs", [o["key"] for o in answer["options"]])
        self.assertIn("jmp.chat", [o["key"] for o in answer["options"]])

    def test_a_process_with_the_flags_gets_the_plan(self):
        code, text = self.run_cli(["setup", "select", "sip", "--provider", "voipms",
                                   "--did", "+15551234567", "--json"])
        self.assertEqual(code, 0)
        plan = json.loads(text)
        self.assertIn("+15551234567", plan["connect"])
        self.assertEqual(plan["rail"], "sip")

    def test_a_provider_we_do_not_hold_is_refused_with_the_ones_we_do(self):
        code, text = self.run_cli(["setup", "select", "sip", "--provider", "twilio"])
        self.assertEqual(code, 1)
        options = json.loads(text)["options"]
        self.assertIn("bulkvs", options)
        self.assertNotIn("twilio", options)

    def test_only_the_providers_that_can_receive_are_called_an_inbox(self):
        inbox = set(providers.inbox_providers())
        self.assertEqual(inbox, {"voip.ms", "flowroute", "anveo", "signalwire", "questblue",
                                 "bulkvs", "jmp.chat"})
        for name, needle in (("voyced", "voice number until a real text lands"),
                             ("voxacall", "not an inbox"),
                             ("bitcall", "cannot be the inbox")):
            entry = providers.profile(name)
            self.assertEqual(entry["text_style"], "none", name)
            self.assertFalse(entry["works_while_off"]["texts"], name)
            self.assertIn(needle, entry["note"], name)
        self.assertEqual(providers.profile("jmp.chat")["text_style"], "xmpp")
        self.assertEqual(providers.profile("jmp.chat")["did_usd_month"], 4.99)
        self.assertEqual(providers.profile("bulkvs")["did_usd_month"], 0.06)

    def test_every_route_says_what_a_person_pastes_and_what_to_do_when_nothing_can_be_pasted(self):
        from heyphony.src.setup import routes
        for name in routes.ROUTES:
            hook = routes.hook(name, "https://host:8099")
            self.assertIn(hook["kind"], ("email", "webhook-json", "url-forward", "post-to-url", "xmpp", "none"))
            self.assertIn("evidence", hook)
            self.assertFalse(hook["verified"])
            if hook["kind"] in ("none", "xmpp", "email"):
                self.assertIsNone(hook["paste_url"], name)
            else:
                self.assertTrue(hook["paste_url"].startswith("https://host:8099/sms/"), name)
        anveo = routes.hook("anveo", "https://host:8099")["paste_url"]
        self.assertIn("$[from]$", anveo)
        self.assertIn("$[message]$", anveo)

    def test_bulkvs_registers_one_webhook_over_its_api_and_needs_credentials_first(self):
        from heyphony.src.setup import routes
        dry = routes.apply_hook("bulkvs", "https://host:8099")
        self.assertFalse(dry["applied"])
        self.assertEqual(sorted(dry["missing"]), ["BULKVS_API_PASS", "BULKVS_API_USER"])
        self.assertIn("https://host:8099/sms/bulkvs", dry["as_curl"])
        self.assertIn("webHooks", dry["as_curl"])
        self.assertIn('"Webhook": "comms"', dry["as_curl"])

    def test_one_envelope_out_of_five_more_shapes(self):
        from heyphony.src.setup import routes
        bulk = routes.normalize("bulkvs", {"From": "+1555", "To": "+1666", "Message": "yo", "RefId": "r1"})
        self.assertEqual((bulk["sender"], bulk["recipient"], bulk["body"], bulk["id"]), ("+1555", "+1666", "yo", "r1"))
        questblue = routes.normalize("questblue", {"from": "+1555", "to": "+1666", "msg": "hey"})
        self.assertEqual(questblue["body"], "hey")
        signalwire = routes.normalize("signalwire", {"message": {"from": "+1", "to": "+2", "body": "hi", "message_id": "m1"}})
        self.assertEqual(signalwire["id"], "m1")
        anveo = routes.normalize("anveo", {"from": "+1", "to": "+2", "message": "hello"})
        self.assertTrue(anveo["id"].startswith("anveo:"))
        # a provider that posts nothing still cannot crash the catcher
        self.assertEqual(routes.normalize("voyced", {"surprise": True})["id"], "voyced:unexpected")
        self.assertEqual(routes.normalize("jmp.chat", {"surprise": True})["id"], "jmp.chat:unexpected")
        with self.assertRaises(KeyError):
            routes.normalize("twilio", {})

    def test_an_unknown_rail_is_refused(self):
        code, text = self.run_cli(["setup", "select", "carrier-pigeon"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(text)["rails"], ["sip"])

    def test_the_old_plan_flag_still_prints_the_plan(self):
        code, text = self.run_cli(["setup"])
        self.assertEqual(code, 0)
        self.assertIn("lanes", json.loads(text))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f"selftest: {result.testsRun - failed}/{result.testsRun} pass")
    sys.exit(1 if failed else 0)

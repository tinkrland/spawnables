"""selftest: the durables contract, proven without a network, a guest or a cloud.

the interesting half of a durable is not "it runs". it is: the answer was committed first, the
isolate was allowed to die, and the second writer was refused. every test here is one of those.
"""
import json
import pathlib
import shutil
import tempfile
import threading
import time
import unittest

from durables import contract
from durables.isolates import InProcess, IsolateError, V8, backend_for
from durables.runtime import DurableError, Host, LeaseLost, Refused
from durables.store import Store, StoreError


def counter(method, args, state):
    n = state.get("n", 0)
    if method == "incr":
        return {"n": n + int(args.get("by", 1))}, {"n": n + int(args.get("by", 1))}
    if method == "alarm":
        return {"n": n + 1, "payload": args}, {"n": n + 1}
    return {"n": n}, state


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="dur-test-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def host(self, idle=30):
        h = Host(self.dir)
        h.define("counter", counter, idle_seconds=idle)
        return h


class TestStore(Base):
    def test_seq_is_assigned_by_the_store(self):
        s = Store(self.dir)
        a = s.append("counter:x", {"kind": "state", "state": {"n": 1}})
        b = s.append("counter:x", {"kind": "state", "state": {"n": 2}})
        self.assertEqual((a["seq"], b["seq"]), (1, 2))

    def test_a_snapshot_covers_the_log_it_truncates(self):
        s = Store(self.dir)
        s.append("counter:x", {"kind": "state", "state": {"n": 5}})
        s.compact("counter:x", {"n": 5})
        state, entries, seq = s.load("counter:x")
        self.assertEqual(state, {"n": 5})
        self.assertEqual(entries, [])
        self.assertGreaterEqual(seq, 1)

    def test_ids_are_addresses_not_paths(self):
        s = Store(self.dir)
        weird = "counter:a/b c:d"
        s.append(weird, {"kind": "state", "state": {"n": 1}})
        self.assertIn(weird, s.actors())
        self.assertEqual(s.load(weird)[0], {"n": 1})

    def test_an_actor_needs_a_name(self):
        with self.assertRaises(StoreError):
            Store(self.dir).actor_dir("")


class TestCommitBeforeAck(Base):
    def test_state_is_on_disk_before_the_caller_hears_it(self):
        h = self.host()
        h.invoke("counter:a", "incr", {"by": 4})
        # a second store, reading the same directory: this is the disk, not the isolate's memory
        self.assertEqual(Store(self.dir).load("counter:a")[0], {"n": 4})

    def test_a_failing_isolate_commits_nothing(self):
        def boom(method, args, state):
            raise RuntimeError("isolate died mid-call")

        h = Host(self.dir)
        h.define("counter", boom, idle_seconds=30)
        with self.assertRaises(RuntimeError):
            h.invoke("counter:a", "incr", {})
        self.assertEqual(Store(self.dir).load("counter:a")[0], {})

    def test_durable_across_a_restart(self):
        h1 = self.host()
        h1.invoke("counter:a", "incr", {"by": 2})
        h2 = self.host()                      # a new host, same state dir
        h2.invoke("counter:a", "incr", {"by": 3})
        self.assertEqual(h2.read("counter:a"), {"n": 5})


class TestIsolateIsACache(Base):
    def test_eviction_keeps_the_state(self):
        h = self.host(idle=0)
        h.invoke("counter:a", "incr", {"by": 7})
        self.assertEqual(h.sweep(), ["counter:a"])
        self.assertEqual(h.invoke("counter:a", "incr", {"by": 1}), {"n": 8})

    def test_a_busy_actor_is_not_swept(self):
        h = self.host(idle=10_000)
        h.invoke("counter:a", "incr", {})
        self.assertEqual(h.sweep(), [])

    def test_read_does_not_wake_an_isolate(self):
        h = self.host(idle=0)
        h.invoke("counter:a", "incr", {"by": 3})
        h.sweep()
        self.assertEqual(h.read("counter:a"), {"n": 3})
        self.assertEqual(h._live, {})


class TestOneWriter(Base):
    def test_a_stale_writer_is_refused(self):
        h1 = self.host()
        h1.invoke("counter:a", "incr", {"by": 1})
        h2 = self.host()                       # takes a newer lease on the same actor
        h2.invoke("counter:a", "incr", {"by": 1})
        with self.assertRaises(LeaseLost):
            h1.invoke("counter:a", "incr", {"by": 1})

    def test_calls_serialize_without_losing_updates(self):
        h = self.host()
        errors = []

        def hammer():
            try:
                for _ in range(10):
                    h.invoke("counter:a", "incr", {"by": 1})
            except Exception as exc:           # noqa: BLE001 - the point is that none appear
                errors.append(exc)

        threads = [threading.Thread(target=hammer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(h.read("counter:a"), {"n": 40})


class TestRefusals(Base):
    def test_native_code_is_refused(self):
        h = self.host()
        for method in ("exec", "spawn"):
            with self.assertRaises(Refused) as got:
                h.invoke("counter:a", method, {})
            self.assertIn("native", str(got.exception) + contract.REFUSED["native-code"])

    def test_a_socket_inside_the_isolate_is_refused(self):
        h = self.host()
        with self.assertRaises(Refused):
            h.invoke("counter:a", "listen", {})

    def test_an_undefined_class_is_refused(self):
        h = self.host()
        with self.assertRaises(DurableError):
            h.invoke("nosuch:a", "incr", {})

    def test_burn_needs_the_id_typed_back(self):
        h = self.host()
        h.invoke("counter:a", "incr", {})
        with self.assertRaises(Refused):
            h.burn("counter:a", confirm="a")
        h.burn("counter:a", confirm="counter:a")
        self.assertEqual(Store(self.dir).load("counter:a")[0], {})


class TestAlarms(Base):
    def test_an_alarm_fires_once_and_carries_its_payload(self):
        h = self.host()
        h.invoke("counter:a", "incr", {"by": 1})
        h.alarm("counter:a", at=time.time() - 1, payload={"why": "test"})
        first = h.tick()
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["out"]["payload"], {"why": "test"})
        self.assertEqual(h.tick(), [])          # fired means fired
        self.assertEqual(h.read("counter:a"), {"n": 2})

    def test_a_future_alarm_does_not_fire_early(self):
        h = self.host()
        h.alarm("counter:a", at=time.time() + 3600)
        self.assertEqual(h.tick(), [])


class TestContract(unittest.TestCase):
    def test_every_placement_says_what_it_needs_and_what_it_has_not_proven(self):
        for name, p in contract.PLACEMENTS.items():
            for field in ("what", "needs", "isolation", "verified"):
                self.assertIn(field, p, f"{name} is missing {field}")
            self.assertTrue(p["verified"], name)

    def test_only_the_host_placement_is_verified(self):
        # a claim of verification for a guest or container would be the drift this repo hunts
        for name in ("guest", "container"):
            self.assertIn("not run here", contract.PLACEMENTS[name]["verified"], name)

    def test_refusals_are_never_empty_and_always_reasoned(self):
        self.assertGreaterEqual(len(contract.REFUSED), 6)
        for key, why in contract.REFUSED.items():
            self.assertGreater(len(why), 30, f"{key} needs a reason, not a word")

    def test_the_card_is_json_and_names_its_sources(self):
        got = json.loads(json.dumps(contract.card()))
        self.assertIn("durable objects", got["sources"])
        self.assertIn("durable actors", got["sources"])

    def test_an_unknown_placement_is_refused(self):
        with self.assertRaises(KeyError):
            contract.placement("moon")

    def test_a_durable_may_not_claim_identity_or_a_kernel(self):
        self.assertIn("identity", contract.REFUSED)
        self.assertIn("kernel-of-its-own", contract.REFUSED)


class TestBackends(unittest.TestCase):
    def test_in_process_is_honest_about_not_being_an_isolate(self):
        self.assertFalse(InProcess().real)

    def test_v8_is_the_real_one(self):
        self.assertTrue(V8("module.exports={handle:()=>({out:1,state:{}})}").real)

    def test_guest_placement_refuses_rather_than_pretending(self):
        with self.assertRaises(IsolateError):
            backend_for("guest")

    def test_v8_refuses_without_node(self):
        real = V8.available
        V8.available = staticmethod(lambda: False)
        try:
            with self.assertRaises(IsolateError):
                V8("module.exports={}").spawn("x", {})
        finally:
            V8.available = staticmethod(real)   # a plain function here would bind as a method


@unittest.skipUnless(V8.available(), "no node on this host")
class TestRealIsolate(unittest.TestCase):
    """the one test that runs javascript in a v8 worker: state crosses, the sandbox holds."""

    SRC = (
        "module.exports = { handle: (state, method, args) => {\n"
        "  const n = (state.n || 0) + (method === 'incr' ? (args.by || 1) : 0);\n"
        "  return { out: { n, process_visible: typeof process !== 'undefined' }, state: { n } };\n"
        "} };\n")

    def test_state_crosses_and_the_sandbox_holds(self):
        iso = V8(self.SRC)
        iso.spawn("counter:a", {})
        try:
            out, state = iso.call("incr", {"by": 3}, {})
            self.assertEqual(out["n"], 3)
            self.assertFalse(out["process_visible"])   # no node globals inside the isolate
            out2, state2 = iso.call("incr", {"by": 2}, state)
            self.assertEqual(out2["n"], 5)
        finally:
            iso.close()

    def test_a_broken_actor_module_is_an_error_not_a_crash(self):
        iso = V8("this is not javascript")
        iso.spawn("counter:a", {})
        try:
            with self.assertRaises(IsolateError):
                iso.call("incr", {}, {})
        finally:
            iso.close()


class TestReadmeKeepsItsNeedles(unittest.TestCase):
    def test_the_readme_states_the_rule_in_the_owners_terms(self):
        import re
        text = re.sub(r"\s+", " ", (pathlib.Path(__file__).resolve().parents[1] /
                                    "durables-readme.md").read_text().lower())
        for needle in ("commit before", "the log is the truth", "expected to die",
                       "one isolate per actor", "never an identity", "v8"):
            self.assertIn(needle, text, needle)


if __name__ == "__main__":
    unittest.main(verbosity=1)

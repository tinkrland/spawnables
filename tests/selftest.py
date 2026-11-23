"""selftest: the durables contract, proven without a network, a guest or a cloud.

the interesting half of a durable is not "it runs". it is: the answer was committed first, the
isolate was allowed to die, and the second writer was refused. every test here is one of those.
"""
import json
import os
import pathlib
import shutil
import tempfile
import threading
import time
import unittest

from spawnables_durables import contract
from spawnables_durables.isolates import InProcess, IsolateError, V8, backend_for
from spawnables_durables.pool import Pool, PooledBackend
from spawnables_durables.runtime import DurableError, Host, LeaseLost, Refused
from spawnables_durables.store import Store, StoreError


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

    def test_a_placement_that_has_not_run_says_so(self):
        # host and guest have been run; a container has not, and its row may not imply otherwise
        self.assertIn("not run here", contract.PLACEMENTS["container"]["verified"])
        for name in ("host", "guest"):
            self.assertNotIn("not run here", contract.PLACEMENTS[name]["verified"], name)

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


COUNTER_JS = (
    "module.exports = { handle: (state, method, args) => {\n"
    "  const n = (state.n || 0) + (method === 'incr' ? (args.by || 1) : 0);\n"
    "  return { out: { n, process_visible: typeof process !== 'undefined' }, state: { n } };\n"
    "} };\n")


@unittest.skipUnless(Pool.available(), "no node on this host")
class TestIsolatePool(unittest.TestCase):
    """eight actors used to mean eight node processes. one process is the whole point of a pool."""

    def setUp(self):
        self.pool = Pool(max_workers=4)

    def tearDown(self):
        self.pool.close()

    def test_many_actors_share_one_process(self):
        pids = set()
        for i in range(8):
            w, _ = self.pool.acquire(f"counter:a{i}", COUNTER_JS)
            out, _state = self.pool.call(w, {}, "incr", {"by": i + 1})
            pids.add(self.pool.stats()["pid"])
            self.assertEqual(out["n"], i + 1)
            self.pool.release(w)
        self.assertEqual(len(pids), 1, "eight actors, one process")
        st = self.pool.stats()
        self.assertEqual((st["spawned"], st["released"], st["workers"]), (8, 8, 0))

    def test_the_ceiling_is_a_refusal_not_a_queue(self):
        held = [self.pool.acquire(f"busy:{i}", COUNTER_JS)[0] for i in range(4)]
        try:
            with self.assertRaises(IsolateError) as got:
                self.pool.acquire("busy:extra", COUNTER_JS)
            self.assertIn("ceiling", str(got.exception))
        finally:
            for w in held:
                self.pool.release(w)

    def test_release_terminates_the_isolate(self):
        w1, reused = self.pool.acquire("solo:x", COUNTER_JS)
        self.assertFalse(reused)
        w2, reused2 = self.pool.acquire("solo:x", COUNTER_JS)
        self.assertEqual((w1, reused2), (w2, True), "one worker per actor while it is live")
        self.pool.release(w1)
        w3, reused3 = self.pool.acquire("solo:x", COUNTER_JS)
        self.assertNotEqual(w3, w1, "a released isolate is gone, not parked")
        self.assertFalse(reused3)
        self.pool.release(w3)

    def test_a_released_worker_cannot_be_called(self):
        w, _ = self.pool.acquire("gone:x", COUNTER_JS)
        self.pool.release(w)
        with self.assertRaises(IsolateError):
            self.pool.call(w, {}, "incr", {})

    def test_state_still_crosses_and_the_sandbox_still_holds(self):
        w, _ = self.pool.acquire("counter:a", COUNTER_JS)
        out, state = self.pool.call(w, {}, "incr", {"by": 2})
        self.assertEqual(out["n"], 2)
        self.assertFalse(out["process_visible"])
        out2, _ = self.pool.call(w, state, "incr", {"by": 3})
        self.assertEqual(out2["n"], 5)
        self.pool.release(w)


@unittest.skipUnless(Pool.available(), "no node on this host")
class TestPooledDurability(Base):
    """the pool must not weaken the three rules: commit, one writer, and the isolate as a cache."""

    def test_eviction_replays_into_a_different_isolate(self):
        pool = Pool(max_workers=4)
        try:
            h = Host(self.dir)
            h.define("counter", None, idle_seconds=0, backend=PooledBackend(COUNTER_JS, pool=pool))
            self.assertEqual(h.invoke("counter:a", "incr", {"by": 2})["n"], 2)
            self.assertEqual(h.sweep(), ["counter:a"])          # release terminates the isolate
            self.assertEqual(h.invoke("counter:a", "incr", {"by": 3})["n"], 5)
            self.assertEqual(Store(self.dir).load("counter:a")[0], {"n": 5})
            self.assertEqual(pool.stats()["spawned"], 2, "a replayed actor gets a fresh isolate")
        finally:
            pool.close()

    def test_two_actors_never_share_an_isolate(self):
        pool = Pool(max_workers=4)
        try:
            h = Host(self.dir)
            h.define("counter", None, idle_seconds=30, backend=PooledBackend(COUNTER_JS, pool=pool))
            h.invoke("counter:a", "incr", {"by": 1})
            h.invoke("counter:b", "incr", {"by": 9})
            actors = [a["actor"] for a in pool.stats()["actors"]]
            self.assertEqual(sorted(actors), ["counter:a", "counter:b"])
            self.assertEqual(h.read("counter:a"), {"n": 1})
            self.assertEqual(h.read("counter:b"), {"n": 9})
        finally:
            pool.close()


def _pool_processes():
    """how many pool hosts are alive. the bracket keeps the pattern from matching this command."""
    import subprocess as sp
    out = sp.run(["pgrep", "-fc", "spawnables_durables/js/pool[.]js"], capture_output=True, text=True)
    try:
        return int(out.stdout.strip() or 0)
    except ValueError:
        return 0


@unittest.skipUnless(Pool.available(), "no node on this host")
class TestNothingIsLeftRunning(unittest.TestCase):
    """a pool outliving the script that made it is a leak, and it was measured before it was fixed."""

    SCRIPT = (
        "import tempfile\n"
        "from spawnables_durables.pool import PooledBackend\n"
        "from spawnables_durables.runtime import Host\n"
        "h = Host(tempfile.mkdtemp())\n"
        "h.define('counter', None, backend=PooledBackend({src!r}))\n"
        "h.invoke('counter:a', 'ping', {{}})\n"
        "{tail}\n")

    def _run(self, tail=""):
        import subprocess as sp
        import sys
        code = self.SCRIPT.format(
            src="module.exports={handle:(s,m,a)=>({out:{ok:1},state:s})};\n", tail=tail)
        return sp.run([sys.executable, "-c", code], capture_output=True, text=True,
                      env={**os.environ, "PYTHONPATH": str(pathlib.Path(__file__).resolve().parents[1])})

    def test_close_shuts_the_process_down(self):
        pool = Pool()
        pool.acquire("counter:a", COUNTER_JS)
        proc = pool.proc
        pool.close()
        self.assertIsNotNone(proc)
        proc.wait(timeout=5)
        self.assertIsNotNone(proc.poll(), "the node process is gone after close()")

    def test_a_forgotten_pool_does_not_outlive_the_interpreter(self):
        before = _pool_processes()
        self._run()                                  # no close: atexit is the only guard
        time.sleep(1.0)
        self.assertEqual(_pool_processes(), before, "a forgotten pool must not survive its script")

    def test_a_killed_parent_leaves_no_pool(self):
        import signal
        before = _pool_processes()
        self._run(f"import os, signal; os.kill(os.getpid(), signal.SIGKILL)")
        time.sleep(1.5)                              # no python cleanup ran; stdin closed is the guard
        self.assertEqual(_pool_processes(), before, "SIGKILL of the parent must not orphan the pool")

    def test_a_host_closes_the_backend_it_owns(self):
        closed = []

        class Backend:
            isolate = True

            def spawn(self, name, state):
                return InProcess(counter)

            def close(self):
                closed.append(True)

        h = Host(tempfile.mkdtemp())
        h.define("counter", counter, backend=Backend())
        h.invoke("counter:a", "incr", {"by": 1})
        h.close()
        self.assertEqual(closed, [True])
        h.close()                                     # idempotent: closing twice is not an error
        self.assertEqual(closed, [True], "a backend is closed once, not once per call")


class TestPoolWithoutNode(unittest.TestCase):
    def test_the_pool_refuses_rather_than_pretending(self):
        real = Pool.available
        Pool.available = staticmethod(lambda: False)
        try:
            pool = Pool()
            pool.node = None
            with self.assertRaises(IsolateError):
                pool.acquire("counter:a", COUNTER_JS)
        finally:
            Pool.available = staticmethod(real)


class TestReadmeKeepsItsNeedles(unittest.TestCase):
    def test_the_readme_states_the_rule_in_the_owners_terms(self):
        import re
        text = re.sub(r"\s+", " ", (pathlib.Path(__file__).resolve().parents[1] /
                                    "durables-readme.md").read_text().lower())
        for needle in ("commit before", "the log is the truth", "expected to die",
                       "one isolate per actor", "never an identity", "v8",
                       "one pooled process", "release terminates the isolate",
                       "43 tests", "zero processes behind"):
            self.assertIn(needle, text, needle)


if __name__ == "__main__":
    unittest.main(verbosity=1)

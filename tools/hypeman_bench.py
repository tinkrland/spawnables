#!/usr/bin/env python3
"""measure standby -> first exec on a real hypeman host.

their readme says restore resumes "in milliseconds". we do not repeat that
number until we have our own: the phone pool's whole value is a guest that is
warm when the agent arrives, so the number that matters is not restore alone,
it is the time from "restore" to "a command has actually returned output".

protocol per iteration (never cold-boot inside the measurement):
  1. create from image, wait running, exec a warm-up (page in the agent)
  2. standby, wait standby
  3. t0 = monotonic, restore, wait running, exec "true", t1
  4. sample = t1 - t0  (restore + scheduling + guest agent round trip)

endpoints used, as registered in their api:
  post /instances, get /instances/{id}/wait?state=, post /instances/{id}/standby,
  post /instances/{id}/restore, get /instances/{id}/exec

usage:
  HYPMAN_API=http://127.0.0.1:8080 HYPMAN_TOKEN=... \\
    python3 tools/hypeman_bench.py --image debian:bookworm-slim -n 20
  python3 tools/hypeman_bench.py --dry-run        # math check, no host, no network
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.request

# a warm phone must be usable by an agent that just arrived. above this the
# pool is doing the agent's waiting for it, which defeats the point.
DEFAULT_THRESHOLD_MS = 1500.0


def percentile(samples, q):
    """nearest-rank percentile; no numpy, no interpolation games."""
    if not samples:
        raise ValueError("no samples")
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(1, min(len(ordered), round(q / 100.0 * len(ordered) + 0.5)))
    return ordered[rank - 1]


def summarize(samples_ms):
    """the reportable shape. p50 for the usual case, p95 because a pool is
    judged by its slow resumes, max because one 40s outlier is a bug."""
    return {
        "n": len(samples_ms),
        "p50_ms": round(percentile(samples_ms, 50), 1),
        "p95_ms": round(percentile(samples_ms, 95), 1),
        "max_ms": round(max(samples_ms), 1),
        "min_ms": round(min(samples_ms), 1),
        "mean_ms": round(statistics.fmean(samples_ms), 1),
    }


def verdict(report, threshold_ms=DEFAULT_THRESHOLD_MS):
    """pass on p95, not on the mean: a pool that is usually fast and
    sometimes awful still feels awful."""
    ok = report["p95_ms"] <= threshold_ms
    return {
        "ok": ok,
        "threshold_ms": threshold_ms,
        "binding": "p95_ms",
        "why": ("p95 within budget" if ok else
                "p95 over budget: the pool would make the agent wait"),
    }


# -- the host side -----------------------------------------------------------

class Host:
    """the thin slice of their api this measurement needs. deliberately not a
    client library: five calls, no retries, so a failure is the host's answer
    rather than a guess we smoothed over."""

    def __init__(self, base, token, timeout=120):
        self.base = base.rstrip("/")
        self.token = token
        self.timeout = timeout

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("authorization", f"bearer {self.token}")
        if data:
            req.add_header("content-type", "application/json")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            raw = r.read()
        return json.loads(raw) if raw else {}

    def wait(self, iid, state, timeout=180):
        return self.call("get", f"/instances/{iid}/wait?state={state}&timeout={timeout}")

    def exec(self, iid, argv, timeout=30):
        return self.call("post", f"/instances/{iid}/exec",
                         {"command": argv, "timeout": timeout})


def measure(host, image, iterations, settle_s=0.0):
    """one warm guest, N standby/restore cycles. returns (samples_ms, cold_ms)."""
    created = host.call("post", "/instances", {"image": image})
    iid = created.get("id") or created.get("name")
    t_cold = time.monotonic()
    host.wait(iid, "running")
    host.exec(iid, ["true"])
    cold_ms = (time.monotonic() - t_cold) * 1000.0

    samples = []
    for _ in range(iterations):
        host.call("post", f"/instances/{iid}/standby", {})
        host.wait(iid, "standby")
        if settle_s:
            time.sleep(settle_s)
        t0 = time.monotonic()
        host.call("post", f"/instances/{iid}/restore", {})
        host.wait(iid, "running")
        host.exec(iid, ["true"])
        samples.append((time.monotonic() - t0) * 1000.0)
    return samples, cold_ms


def dry_run(iterations):
    """plausible numbers so the math and the report shape are reviewable when
    no host is available. NEVER reported as a measurement."""
    import random
    rng = random.Random(7)
    return [rng.gauss(950, 180) for _ in range(iterations)], 4100.0


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--api", default=os.environ.get("HYPMAN_API", "http://127.0.0.1:8080"))
    p.add_argument("--token", default=os.environ.get("HYPMAN_TOKEN", ""))
    p.add_argument("--image", default="debian:bookworm-slim")
    p.add_argument("-n", "--iterations", type=int, default=20)
    p.add_argument("--threshold-ms", type=float, default=DEFAULT_THRESHOLD_MS)
    p.add_argument("--settle", type=float, default=0.0,
                   help="seconds to idle after standby, to test decay")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)

    if a.dry_run:
        samples, cold = dry_run(a.iterations)
        source = "dry-run (synthetic, not a measurement)"
    else:
        if not a.token:
            print("HYPMAN_TOKEN is required against a real host", file=sys.stderr)
            return 2
        samples, cold = measure(Host(a.api, a.token), a.image, a.iterations, a.settle)
        source = f"{a.api} image={a.image}"

    report = summarize(samples)
    report["cold_boot_ms"] = round(cold, 1)
    report["source"] = source
    report["verdict"] = verdict(report, a.threshold_ms)
    print(json.dumps(report, indent=2))
    return 0 if (a.dry_run or report["verdict"]["ok"]) else 1


if __name__ == "__main__":
    sys.exit(main())

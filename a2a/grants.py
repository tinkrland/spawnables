"""a2a: a share between two agents, as data, with its refusals attached.

the transport moves bytes; this module decides whether they may move at all. every rule here is a
value rather than a sentence in a readme, so a card, a cli and a test read the same limits.
"""
from __future__ import annotations

import posixpath

MB = 1024 * 1024

DEFAULT_MAX_BYTES = 512 * MB
CEILING_MAX_BYTES = 2 * 1024 * MB
MIN_HOURS = 1
MAX_HOURS = 24
MAX_PATHS = 16

DIRECTIONS = {
    "send": {"who_acts": "the sender", "command": "croc send",
             "means": "one direction, from this agent to one peer"},
    "receive": {"who_acts": "the receiver", "command": "croc <code>",
                "means": "the same share seen from the other end"},
    "both": {"who_acts": "neither alone", "command": None,
             "means": "not one share: two shares, each with its own purpose and expiry",
             "refused_as": "both-is-two-shares"},
}

# the recipient of a file never writes over its own work because someone else sent a name
DESTINATION = {
    "quarantine_dir": "a folder the receiver owns, one per share",
    "on_collision": "stop, and let the receiver's own rule decide; never overwrite",
}

TRANSPORTS = {
    "croc": {
        "chosen": True,
        "verified": "read from github.com/schollz/croc readme, 2026-11-02",
        "why": "p2p with relay fallback, end to end encryption by pake over a code phrase, multiple "
               "files and folders, resume, no port forwarding, one static binary on linux, macos and "
               "windows, which matters when the fleet is not one operating system",
        "capability": "the code phrase is the capability, so its exchange is the controlled moment",
        "shape": "one-shot handoff",
    },
    "magic-wormhole": {
        "chosen": False,
        "verified": "shape only: spake2 pairing against a rendezvous server, python library",
        "why": "the same idea with a python library and a rendezvous server instead of a code on a cli",
        "cost": "a long lived python dependency per member is heavier than a binary that exists only "
                "while a transfer runs",
        "shape": "one-shot handoff",
    },
    "syncthing": {
        "chosen": False,
        "refused": "continuous-sync-is-not-a-grant",
        "verified": "shape only: continuous two-way sync between device ids",
        "why": "continuous sync means the file lives on both sides for as long as the folder is "
               "shared, so revoked becomes a promise about a peer's behaviour instead of a fact "
               "about a capability",
        "shape": "standing shared folder, a fleet decision for later",
    },
    "overlay-network": {
        "chosen": False,
        "refused": "routing-is-not-a-file-lane",
        "why": "putting members on one address space decides reachability, not which paths, in which "
               "direction, until when",
        "shape": "routing",
    },
}

SECRET_SHAPED = (".ssh", ".gnupg", ".aws", ".netrc", ".config/gcloud", "id_rsa", "id_ed25519",
                 ".pem", ".key", ".p12", ".kdbx")

REFUSED = {
    "outside-the-fleet": "trust is the owner's set of principals; there is nothing outside it to be "
                         "generous towards",
    "unscoped": "a whole home directory, /, or a path list that names no files",
    "no-purpose": "a grant nobody can explain in a sentence is a grant that gets renewed forever",
    "no-expiry": "a share with no end is a share nobody is watching",
    "broadcast": "fan-out is one share per peer, each with its own purpose and expiry, so revoking "
                 "one does not leave eight",
    "both-is-two-shares": "both directions is two grants, not one, because each half has its own "
                          "purpose and can be revoked alone",
    "silent-overwrite": "replace is an act the receiver takes, never a side effect of arriving",
    "secret-shaped-path": "credentials move through the vault plane, not a file share",
    "borrowed-identity": "an agent may send as itself; a from it does not hold is refused before any "
                         "transport starts",
    "auto-accept": "the receiving side is a decision; only an owner-written standing rule can be "
                   "scoped to a sender and a path",
    "over-ceiling": "bigger than the ceiling means the wrong tool, not a bigger ceiling",
}


def _norm(path):
    return posixpath.normpath(str(path or "").strip())


def path_faults(paths):
    """why these paths cannot be a scope. returns named faults, not prose."""
    faults = []
    if not paths:
        return ["unscoped"]
    if len(paths) > MAX_PATHS:
        faults.append("unscoped")
    for raw in paths:
        p = str(raw or "")
        if ".." in p.split("/"):  # judged before normalising, or /var/../etc folds into a clean path
            faults.append("unscoped")
            continue
        n = _norm(p)
        if not p or n in ("", ".", "/", "~", "..") or n.startswith("~"):
            faults.append("unscoped")
            continue
        if ".." in n.split("/"):
            faults.append("unscoped")
        if "*" in p or "?" in p or "[" in p:
            faults.append("unscoped")  # a glob is a scope that can change meaning later
        low = n.lower()
        if any(marker in low for marker in SECRET_SHAPED):
            faults.append("secret-shaped-path")
    return sorted(set(faults))


def check(share, fleet=None):
    """(ok, faults). fleet is an iterable of principals allowed to take part."""
    faults = []
    direction = share.get("direction")
    if direction == "both":
        faults.append("both-is-two-shares")
    elif direction not in DIRECTIONS:
        faults.append("unscoped")
    sender, peer = share.get("from"), share.get("to")
    if not sender or not peer:
        faults.append("borrowed-identity")
    elif sender == peer:
        faults.append("unscoped")  # a share to yourself grants nothing
    if fleet is not None:
        allowed = set(fleet)
        if sender not in allowed or peer not in allowed:
            faults.append("outside-the-fleet")
    if not str(share.get("purpose") or "").strip():
        faults.append("no-purpose")
    hours = share.get("expires_in_hours")
    if hours is None:
        faults.append("no-expiry")
    elif not isinstance(hours, (int, float)) or not MIN_HOURS <= hours <= MAX_HOURS:
        faults.append("no-expiry")
    size = share.get("max_bytes", DEFAULT_MAX_BYTES)
    if not isinstance(size, int) or size <= 0 or size > CEILING_MAX_BYTES:
        faults.append("over-ceiling")
    faults.extend(path_faults(share.get("paths") or []))
    if share.get("overwrite") is True:
        faults.append("silent-overwrite")
    if share.get("auto_accept") is True:
        faults.append("auto-accept")
    return (not faults, sorted(set(faults)))


def plan(share, fleet=None, transport="croc", code=None):
    """the exact two commands, or the named reasons nothing runs."""
    ok, faults = check(share, fleet)
    if not ok:
        return {"ok": False, "faults": faults,
                "why": {f: REFUSED.get(f, "unnamed fault") for f in faults},
                "commands": [], "transferred": False}
    t = TRANSPORTS.get(transport) or {}
    if not t.get("chosen"):
        return {"ok": False, "faults": ["transport-not-chosen"],
                "why": {"transport-not-chosen": t.get("refused") or "not the chosen transport"},
                "commands": [], "transferred": False}
    paths = [_norm(p) for p in share["paths"]]
    if share["direction"] == "send":
        commands = [["croc", "send", *paths]]
        note = "the code croc prints is the capability: send it out of band, to the peer specifically"
    else:
        if not code:
            return {"ok": False, "faults": ["code-required"],
                    "why": {"code-required": "a receive needs the code the sender printed, and this "
                                             "lane never invents one"},
                    "commands": [], "transferred": False}
        commands = [["croc", str(code)]]
        note = "writes into the receiver's quarantine dir; a collision stops rather than replaces"
    return {"ok": True, "faults": [], "transport": transport, "direction": share["direction"],
            "paths": paths, "expires_in_hours": share["expires_in_hours"],
            "max_bytes": share.get("max_bytes", DEFAULT_MAX_BYTES),
            "destination": DESTINATION, "commands": commands, "note": note,
            "transferred": False,
            "why_not_done": "this returns the plan; nothing is executed here"}


def card():
    """what a ui or an agent reads before offering the verb at all."""
    return {"name": "a2a", "state": "designed",
            "evidence": "grant model, limits and refusals are data and tested; no transfer has run",
            "directions": sorted(DIRECTIONS), "transports": {k: v.get("chosen") for k, v in TRANSPORTS.items()},
            "limits": {"default_max_bytes": DEFAULT_MAX_BYTES, "ceiling_max_bytes": CEILING_MAX_BYTES,
                       "min_hours": MIN_HOURS, "max_hours": MAX_HOURS, "max_paths": MAX_PATHS},
            "refused": sorted(REFUSED), "destination": DESTINATION}

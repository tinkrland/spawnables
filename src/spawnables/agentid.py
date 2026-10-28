"""agent stable ids: cryptographic, unalterable, distinct from usernames.

a username is a label - mutable, cosmetic, for humans. the stable id is
the principal: sha256 of a seed minted once at registration, stored
sealed by the caller (the vault), never derived from the username, and
never changed by renaming. grants bind to the stable id, so a rename
moves nothing and a spoofed label grants nothing.

stdlib only: the id is a sha256 commitment of the seed (sha256 of
domain + seed), so holding the seed proves the id and nothing else
does. asymmetric signatures are the upgrade path if a dependency is
ever allowed; the commitment is unforgeable in practice and the
protocol is honest about being a bearer-proof, not a signature.
"""
import hashlib
import json
import secrets
import time
from pathlib import Path

DOMAIN = b"spawnables-agent-v1"


def stable_id_for(seed):
    """the id commits to the seed; usernames never enter the hash."""
    return hashlib.sha256(DOMAIN + b"\x00" + seed.encode()).hexdigest()


def prove(stable_id, seed):
    """holding the seed proves the id; nothing else does."""
    return stable_id_for(seed) == stable_id


class AgentRegistry:
    """durable principal records; the seed never lands in the file."""

    def __init__(self, path):
        self.path = Path(path)
        self.agents = []
        if self.path.is_file():
            self.agents = json.loads(self.path.read_text())

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.agents, indent=2) + "\n")

    def register(self, username, seed=None):
        """mint a principal; returns (record, seed) - the seed is handed
        out exactly once, to be sealed in the vault by the caller."""
        if seed is None:
            seed = secrets.token_hex(32)
        rec = {"stable_id": stable_id_for(seed),
               "username": username,
               "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        self.agents.append(rec)
        self._save()
        return rec, seed

    def rename(self, stable_id, username):
        """a label change; the principal does not move."""
        for rec in self.agents:
            if rec["stable_id"] == stable_id:
                rec["username"] = username
                self._save()
                return rec
        raise KeyError(f"no agent {stable_id}")

    def username_of(self, stable_id):
        for rec in self.agents:
            if rec["stable_id"] == stable_id:
                return rec["username"]
        return stable_id  # unknown principal: show the id, never guess

    def find(self, stable_id):
        for rec in self.agents:
            if rec["stable_id"] == stable_id:
                return rec
        return None

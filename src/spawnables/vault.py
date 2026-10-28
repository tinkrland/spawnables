"""the vault: secrets never ride in the order, never ride in logs.

an order stores references (@@vault:wg-main@@); at exec time the
provisioner resolves refs against a vault backend. the value travels
to the adapter (the command must actually run) but never to the event
stream: emitted labels keep the ref, logs never keep the value.

handoffs are single-use, appiary-style: an agent granted drive access
on a machine redeems a token once and the token is shredded on
redemption. expired tokens are refused and shredded too.

backends:
- DictBackend: in-memory, for tests and process-local use.
- FernetFileBackend: sealed at rest with fernet (aes-128-cbc + hmac)
  under a master key from env SPAWNABLES_MASTER_KEY, file mode 0600.
  without the cryptography package the backend refuses to store -
  fail closed rather than plaintext at rest.
"""
import json
import os
import re
import time
import uuid

REF_RE = re.compile(r"@@vault:([a-z0-9_.-]+)@@")


class VaultError(Exception):
    pass


class HandoffError(VaultError):
    pass


def refs_in(text):
    """the vault refs a command/label carries."""
    return REF_RE.findall(text or "")


class DictBackend:
    """in-memory backend; tests and single-process runners."""

    def __init__(self):
        self._d = {}

    def put(self, name, value):
        self._d[name] = value

    def get(self, name):
        try:
            return self._d[name]
        except KeyError:
            raise VaultError(f"vault has no secret named '{name}'")

    def delete(self, name):
        self._d.pop(name, None)

    def exists(self, name):
        return name in self._d


class FernetFileBackend:
    """sealed-at-rest file backend. fail closed without cryptography
    or SPAWNABLES_MASTER_KEY - plaintext at rest is never a fallback."""

    def __init__(self, path=None, master_key=None):
        try:
            from cryptography.fernet import Fernet  # noqa: F401
        except ImportError:
            raise VaultError(
                "sealed storage needs the cryptography package "
                "(pip install cryptography); the vault refuses plaintext at rest"
            )
        key = master_key or os.environ.get("SPAWNABLES_MASTER_KEY")
        if not key:
            raise VaultError("SPAWNABLES_MASTER_KEY is not set; the vault refuses to open")
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        self.path = path or os.path.join(
            os.environ.get("SPAWNABLES_VAULT_PATH", "."), "vault.json")
        self._d = {}
        if os.path.exists(self.path):
            blob = json.loads(open(self.path).read())
            self._d = {k: self._fernet.decrypt(v.encode()).decode()
                       for k, v in blob.items()}

    def _flush(self):
        payload = {k: self._fernet.encrypt(v.encode()).decode() for k, v in self._d.items()}
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def put(self, name, value):
        self._d[name] = value
        self._flush()

    def get(self, name):
        try:
            return self._d[name]
        except KeyError:
            raise VaultError(f"vault has no secret named '{name}'")

    def delete(self, name):
        self._d.pop(name, None)
        self._flush()

    def exists(self, name):
        return name in self._d


class Vault:
    def __init__(self, backend=None):
        self.backend = backend or DictBackend()
        self._handoffs = {}

    # -- secrets -------------------------------------------------------------

    def put(self, name, value):
        self.backend.put(name, value)

    def get(self, name):
        return self.backend.get(name)

    def delete(self, name):
        self.backend.delete(name)

    def exists(self, name):
        return self.backend.exists(name)

    def resolve(self, text):
        """replace every @@vault:ref@@ with its value. missing refs
        raise VaultError - the caller fails closed, never silently
        ships an unresolved ref to the guest."""
        out = text or ""
        for ref in sorted(set(refs_in(out))):
            out = out.replace(f"@@vault:{ref}@@", self.backend.get(ref))
        return out

    # -- handoffs (single-use) ------------------------------------------------

    def issue_handoff(self, secret_names, ttl_seconds=300):
        """mint a single-use token over the named secrets."""
        names = tuple(secret_names)
        if not names:
            raise HandoffError("a handoff names at least one secret")
        for n in names:
            if not self.backend.exists(n):
                raise VaultError(f"vault has no secret named '{n}'")
        token = uuid.uuid4().hex
        self._handoffs[token] = {"refs": names,
                                 "expires": time.time() + ttl_seconds}
        return token

    def redeem(self, token):
        """one redemption per token; then it is shredded."""
        h = self._handoffs.pop(token, None)
        if h is None:
            raise HandoffError("unknown or already-redeemed handoff token")
        if time.time() > h["expires"]:
            raise HandoffError("handoff token expired; issue a fresh one")
        return {n: self.backend.get(n) for n in h["refs"]}

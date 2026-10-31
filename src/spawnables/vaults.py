"""the owner's vaults, as sources the main agent can ask for one value.

kernel.sh ships integrations (1password among them) so an agent can use a credential
without the credential being the agent's to keep. this is the same shape for the four
vaults we actually run into, and it obeys the rule the credential plane already states:
resolution happens on the **control plane**, at use time, and the guest gets a value, never
a vault login. nothing here signs anything into a guest, and nothing here caches.

    source      binary      auth (owner's, set once)                      resolve
    1password   op          OP_SERVICE_ACCOUNT_TOKEN                      op read op://vault/item/field
    bitwarden   bw          BW_CLIENTID + BW_CLIENTSECRET + BW_PASSWORD   bw get password item
    vaultwarden bw          same as bitwarden, pointed at our own server  bw config server <url>
    protonpass  pass-cli    PROTON_PASS_PERSONAL_ACCESS_TOKEN (+ reason)  pass-cli item view pass://v/i/f

two things worth knowing before reading further:

- a **code** is available from all four (`kind="totp"`), which is why 2fa needs no app on
  the agent's side: ask the vault for six digits, type them in. a seed never travels.
- **auth is not part of the resolve path.** `bw login`, `op signin` and `pass-cli login` are
  the owner's one-time acts on the control plane; a resolve that could log in is a resolve
  that could strand a session somewhere. the suite asserts no resolve command logs in.
"""
import os
import shutil
import subprocess
import urllib.parse

REF_SCHEMES = {"op": "1password", "bw": "bitwarden", "pass": "protonpass"}

SOURCES = {
    "1password": {
        "binary": "op",
        "licence": "proprietary (proton-free comparison: the cli is free to use, the service is not)",
        "kind": "hosted",
        "auth_env": ["OP_SERVICE_ACCOUNT_TOKEN"],
        "login_hint": "owner runs `op signin` once, or mints a service account token; the token is the auth",
        "schemes": ["op"],
        "install": "brew install 1password-cli, or the .pkg from 1password.com/downloads/command-line",
    },
    "bitwarden": {
        "binary": "bw",
        "licence": "gpl-3.0 (cli) / proprietary service",
        "kind": "hosted",
        "auth_env": ["BW_CLIENTID", "BW_CLIENTSECRET", "BW_PASSWORD"],
        "login_hint": "owner runs `bw login --apikey` then `bw unlock`; the session, not the password, is passed in",
        "schemes": ["bw"],
        "install": "npm i -g @bitwarden/cli, or the standalone binary from github.com/bitwarden/clients",
    },
    "vaultwarden": {
        "binary": "bw",
        "licence": "agpl-3.0 (server) + gpl-3.0 (cli)",
        "kind": "self-hosted",
        "auth_env": ["BW_CLIENTID", "BW_CLIENTSECRET", "BW_PASSWORD", "SPAWNABLES_VAULTWARDEN_URL"],
        "login_hint": ("owner runs `bw config server <url>` once against the vaultwarden container "
                       "(catalog port 8222), then logs in there; no bitwarden account exists"),
        "schemes": ["bw"],
        "install": "same cli as bitwarden; the difference is the server, not the client",
    },
    "protonpass": {
        "binary": "pass-cli",
        "licence": "gpl-3.0",
        "kind": "hosted",
        "auth_env": ["PROTON_PASS_PERSONAL_ACCESS_TOKEN"],
        "login_hint": ("owner mints an *agent* token (`pass-cli agent create <name> --vault <v>`) so every "
                       "read is audited against a reason; `pass-cli login` runs on the control plane only"),
        "schemes": ["pass"],
        "install": "build from github.com/protonpass/pass-cli, or the release binary for your platform",
    },
}

# the reason is mandatory for audited reads, so it is not optional here either
REASON_ENV = "PROTON_PASS_AGENT_REASON"


class VaultSourceError(Exception):
    pass


def source_for(ref):
    """a provider for a reference, from its scheme. refusals name what we do accept."""
    scheme = urllib.parse.urlparse(str(ref)).scheme
    name = REF_SCHEMES.get(scheme)
    if not name:
        raise VaultSourceError(
            f"unknown vault reference scheme {scheme!r}; refs look like op://vault/item/field, "
            "bw://item/field or pass://vault/item/field")
    return name


def components(ref):
    """a ref as (provider, parts) without ever asking the network what it means."""
    provider = source_for(ref)
    u = urllib.parse.urlparse(str(ref).strip())
    parts = ([u.netloc] if u.netloc else []) + [x for x in u.path.strip("/").split("/") if x]
    if provider == "1password" and len(parts) not in (2, 3):
        raise VaultSourceError("op refs are op://vault/item/field (or op://vault/item for a code)")
    if provider in ("bitwarden", "vaultwarden"):
        if not 1 <= len(parts) <= 2:
            raise VaultSourceError("bw refs are bw://item/field")
        if len(parts) == 1:
            parts = [parts[0], "password"]
    if provider == "protonpass" and len(parts) not in (2, 3):
        raise VaultSourceError("pass refs are pass://vault/item/field")
    return provider, parts


def command(ref, kind="field", provider=None, env=None):
    """the argv for one resolve. pure: no io, no side effects, testable to the letter.

    `kind="totp"` asks for a code instead of a stored value, which is the point of the whole
    module: the agent gets six digits and the seed stays where it lives.
    """
    provider = provider or source_for(ref)
    _, parts = components(ref)
    if provider == "1password":
        if kind == "totp":
            return ["op", "item", "get", parts[-1], "--otp"]
        if len(parts) != 3:
            raise VaultSourceError("op://vault/item/field needs all three parts to read a value")
        return ["op", "read", f"op://{parts[0]}/{parts[1]}/{parts[2]}"]
    if provider in ("bitwarden", "vaultwarden"):
        session = (env or {}).get("BW_SESSION")
        flag = ["--session", session] if session else []
        sub = "totp" if kind == "totp" else "password"
        return ["bw", "get", sub, parts[0]] + flag
    if provider == "protonpass":
        if kind == "totp":
            return ["pass-cli", "item", "view", f"pass://{parts[0]}/{parts[1]}?totp=code"]
        return ["pass-cli", "item", "view", f"pass://{parts[0]}/{parts[1]}/{parts[2]}"]
    raise VaultSourceError(f"no resolve path for {provider}")


def missing_auth(provider, env=None):
    """what auth is absent, named exactly, before a binary is even called."""
    env = os.environ if env is None else env
    spec = SOURCES[provider]
    needed = [k for k in spec["auth_env"] if not env.get(k)]
    if provider == "protonpass" and env.get("PROTON_PASS_PERSONAL_ACCESS_TOKEN"):
        # an agent token without a reason is refused by the cli itself; say it here instead
        if not env.get(REASON_ENV):
            needed.append(REASON_ENV)
    return needed


def check(env=None, which=shutil.which):
    """who is usable right now, in the shape the gui and the agent both read."""
    env = os.environ if env is None else env
    out = {}
    for name, spec in SOURCES.items():
        binary = bool(which(spec["binary"]))
        missing = missing_auth(name, env)
        out[name] = {
            "binary": spec["binary"],
            "installed": binary,
            "kind": spec["kind"],
            "licence": spec["licence"],
            "auth_missing": missing,
            "usable": binary and not missing,
            "login": spec["login_hint"],
            "install": spec["install"],
        }
    return out


def resolve(ref, kind="field", env=None, run=subprocess.run, audit=None):
    """one value, or one code. on the control plane, at use time, never cached.

    `audit` receives {provider, ref, kind} and never the value: a record of what was asked for
    is useful, a record of what came back is a leak that outlives the secret.
    """
    env = os.environ if env is None else env
    provider = source_for(ref)
    missing = missing_auth(provider, env)
    if missing:
        raise VaultSourceError(
            f"{provider} is not authenticated: set {', '.join(missing)} "
            f"({SOURCES[provider]['login_hint']})")
    argv = command(ref, kind=kind, provider=provider, env=env)
    if audit:
        audit({"provider": provider, "ref": str(ref), "kind": kind})
    try:
        proc = run(argv, capture_output=True, text=True, env=dict(env), shell=False, timeout=60)
    except FileNotFoundError:
        raise VaultSourceError(
            f"{SOURCES[provider]['binary']} is not installed ({SOURCES[provider]['install']})")
    except subprocess.TimeoutExpired:
        raise VaultSourceError(f"{provider} did not answer in 60s")
    if proc.returncode != 0:
        # stderr is the cli's own words, and it is the one place a hint lives
        raise VaultSourceError(
            f"{provider} refused ({proc.returncode}): {(proc.stderr or proc.stdout or '').strip()[:300]}")
    value = (proc.stdout or "").strip()
    if not value:
        raise VaultSourceError(f"{provider} returned nothing for {ref}")
    return value


def agent_card():
    """what the main agent is allowed to believe about this, in one dict.

    the same job kernel's integration page does: tell the agent the shape of the deal
    before it plans around a capability that is not there.
    """
    return {
        "can": [
            "resolve one value at use time: vaults.resolve('op://work/github/pat')",
            "ask any of the four for a totp code: kind='totp' -> six digits to type",
            "name a provider's readiness: vaults.check() -> installed / auth_missing / usable",
        ],
        "cannot": [
            "hold a vault session in a guest: auth is the owner's, on the control plane",
            "cache or log a value: resolve() takes an audit hook that only sees the ref",
            "sign in for you: login is a one-time owner act, and no resolve command logs in",
            "read a vaultwarden account that does not exist: vaultwarden is our own server",
        ],
        "sources": {k: {"kind": v["kind"], "licence": v["licence"], "schemes": v["schemes"]}
                    for k, v in SOURCES.items()},
        "rule": "a value travels once, in memory, to the thing that must use it. a code is the same deal with a shorter life",
    }

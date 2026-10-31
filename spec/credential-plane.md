# the credential plane: who holds what, and what can leave a guest

owner asked (2026-11-01): can temporary devices hand data to durable ones; how do we
do logins without 1password sitting in every guest; and can the 2fa qr module carry
authenticator enrollment. this file answers the three with sources.

## the distinction everything else hangs off

**a password is a secret. being logged in is state.** a vault brokers the first. nobody
brokers the second, because the second is a cookie jar bound to a device the site has
already fingerprinted. any design that "logs the agent in without the login" is really
choosing where the cookie lives, not whether it exists.

so there are two planes, and they must not be confused:

| plane | what it holds | who holds it | where it lives |
| --- | --- | --- | --- |
| api credentials | keys, pats, tokens | the broker, never the guest | outside the guest |
| site sessions | cookies, device binding | the pinned guest profile | inside one identity |

## plane one: brokered api credentials (infisical agent vault)

verified from github.com/Infisical/agent-vault (2.5k stars, go, open source, docs at
docs.agent-vault.dev): a credential **proxy**, not a secrets api. the agent is pointed
at it with `HTTPS_PROXY`, holds dummy placeholders like `__github_pat__`, and the vault
substitutes the real value or replaces the auth header on the way out. management ui/api
on 14321, mitm proxy on 14322, injected values never returned to the agent. egress
filtering (`unmatched_host_policy=deny` rejects unknown hosts with 403), request
logging, master password unset from the process after first read, pluggable store
(local encrypted, or the infisical platform for dynamic secrets). it is designed to be
deployed on a **different machine** from the agent, which is exactly our shape: vault on
the control plane, guests hold nothing.

why this beats putting 1password in the guest: prompt injection cannot exfiltrate what
the guest never possesses, and the log becomes evidence rather than memory.

## plane two: 1password's real role

kernel ships a 1password integration ("use credentials from your 1password vaults",
under credentials/identity/payments, per kernel.sh/docs/integrations/overview). good
precedent, right idea, wrong layer for us: 1password is the **owner's** vault, not the
agent's runtime. it is the source of truth for the human's items; the agent should reach
them through a broker at use time, never by signing 1password itself into a guest. the
owner's instinct is correct: 1password logged in everywhere is a device-linking tell, and
the fix is not to log it in.

correction to keep on file (owner, nov 2026): i wrote "bitbucket" where they said **bitwarden**.
neither appears in the kernel integrations list i read, so the honest line is: 1password is
confirmed there, bitwarden is not confirmed either way, and vaultwarden is our own service entry
rather than an integration.

## two-factor: the app is not on the critical path

an authenticator app stores an `otpauth://` uri. a code is a computation over that uri,
not a feature of an app. we already decode the qr (`twofa.py`), so the agent's side is:
decode the qr the service shows, seal the uri in the vault, compute codes at use time.
the app choice matters only for the human holding the same seed later.

correction on file (nov 2026, twice): **proton authenticator** is open source, and the owner
was right about where. the code is under the **protonpass** organisation, not protonmail:

| repo | language | licence | note |
| --- | --- | --- | --- |
| `github.com/protonpass/android-authenticator` | kotlin | gpl-3.0 | "source code for the Proton Authenticator Android application" |
| `github.com/protonpass/ios-authenticator` | swift | gpl-3.0 | "iOS client for Proton Authenticator" |

verified from the github api on 2026-11-01 (both repos public, both LICENSE files say gpl-3.0
or later). so the open-source claim is backed by source now, not by a marketing page, and my
earlier "no repo found" note was wrong in a specific way worth recording: i searched
`github.com/ProtonMail` and an org search that returns nothing when the org is wrong does not
prove absence. the lesson is the same one this file keeps teaching: name the query, not the void.

what is still unverified: the **desktop** clients. proton's site lists mac, linux and windows
apps, and that organisation contains exactly two authenticator repos (github search,
`authenticator user:protonpass`, total 2), so the desktop source is either elsewhere or not
published. nothing here needs it either way.

the practical consequence, now that the mobile source is public: if we ever have to hand a seed
back to a person, the app's own import format is readable from the repo instead of guessed from
a screenshot of a settings screen. that is the whole difference between "an app we trust" and
"code we can check", and it is why proton authenticator stays the recommended human copy.

## both ways: the phone enrols, the desktop computes

the owner's observation is the design, and it is worth writing in their words: services
hand out a qr **during setup** and their flow assumes a phone will scan it, and after that
the code is only ever wanted on a desktop. so the phone is needed exactly once.

- **enrolment (phone):** the ceremony is mobile-shaped, so let it be. we decode the qr from a
  screenshot (`decode_command`) and seal the seed, which also means the qr image never has to
  be pasted into a chat with an agent, and a second manual copy never happens.
- **steady state (desktop):** `twofa.code_for(public, store)` asks the seed store for a *code*
  and gets thirty seconds of arithmetic. the seed never leaves the store, the code is computed
  where the store lives, and it is verified against the rfc 6238 vector in the suite.

**not through agent-vault** (owner, nov 2026, and the reasoning holds up): agent-vault exists to
substitute credentials in **outbound http**, where a placeholder in a header becomes a real token
on the way out. a totp is neither outbound nor substitutable: it is arithmetic over a seed we
already hold. routing it through the proxy would add a hop, a root ca and a runtime dependency to
a computation that costs microseconds, and would put a seed-shaped thing on a network path for no
reason. so the proxy keeps its lane (api credentials) and 2fa does not touch it.

what that leaves, honestly: the code still has to be *typed* somewhere, because a totp is a form
field and not a header. the agent types it, or browser automation in the guest does. that is the
whole mechanism, and it needs no proxy at all.

the sentence to keep: **a code travels, a seed does not.** a seed in two apps is two devices
forever, which is a fine thing for a person to want and a pointless thing for an agent to keep.

three rules, because a seed is an identity: one seed per identity; never copy a seed to
a second guest; seal backup codes beside the seed, they are the recovery lane and the
first thing a lost device story needs.

## what can leave a temporary guest

| thing | can move? | why |
| --- | --- | --- |
| artifacts, documents, project files | yes | the work is not the machine |
| app data via the app's own export | yes | it is a file, and the app authored it |
| clipboard, notes, downloads | yes | ordinary files |
| a login session | only with the identity | otherwise you have two devices, one persona |
| a totp seed | only with the identity | same reason, and it is a credential |
| device identity / fingerprint state | never | it is the thing being pinned, not cargo |

the verbs: `export` (guest -> control plane), `verify` (checksum + manifest), `import`
(control plane -> a named durable guest), and `burn` refuses until the export receipt
exists. the anti-pattern the receipt prevents: moving a session out of a throwaway guest
into a durable one while the throwaway keeps running, which reads to the site as the
same person on two devices.

## open, honestly

- agent-vault licence text not read yet (repo has LICENSE; confirm before shipping).
- the proxy needs its root ca trusted inside each guest; our provisioner can do that,
  but it is a provisioner step that must be written, not assumed.
- kernel's bitwarden integration unconfirmed (1password is confirmed); proton authenticator's mobile repos confirmed under `protonpass/`, desktop source not found.

## the four vaults, as sources (aug 2026 request: "like kernel.sh has")

kernel's integration page does one thing well: it tells the agent the shape of the deal before
it plans around a capability. `spawnables/vaults.py` is the same deal for the vaults we actually
run into, and it is a **resolve** rail, not a sync rail: one value at use time, on the control
plane, never cached, never signed into a guest.

| source | binary | auth the owner sets once | resolve | code |
| --- | --- | --- | --- | --- |
| 1password | `op` | `OP_SERVICE_ACCOUNT_TOKEN` | `op read op://vault/item/field` | `op item get item --otp` |
| bitwarden | `bw` | `BW_CLIENTID`, `BW_CLIENTSECRET`, `BW_PASSWORD` | `bw get password item --session …` | `bw get totp item` |
| vaultwarden | `bw` | same, plus `SPAWNABLES_VAULTWARDEN_URL` | same cli, our server on 8222 | same |
| proton pass | `pass-cli` | `PROTON_PASS_PERSONAL_ACCESS_TOKEN` + `PROTON_PASS_AGENT_REASON` | `pass-cli item view pass://v/i/f` | `…?totp=code` |

three decisions inside that table, each with a reason:

- **refs are native.** `op://`, `bw://`, `pass://` keep the semantics people already know instead
  of inventing a fourth syntax. the scheme picks the source; nothing guesses.
- **login is not in the resolve path.** `op signin`, `bw login`, `pass-cli login` are the owner's
  one-time acts on the control plane. a resolve that could log in is a resolve that could strand a
  live session on a machine that later gets burned. the suite asserts no resolve command logs in.
- **proton pass wants a reason.** its cli audits agent reads against `PROTON_PASS_AGENT_REASON`, so
  we require it too rather than silently passing an empty one. vaultwarden is the reverse case and
  worth stating: it is our own server, there is no bitwarden account behind it, and the `bw` cli is
  just the client.

the code column is the answer to 2fa, again: six digits from whichever vault holds the seed, typed
into the form by the agent. no app on our side, no proxy, no seed in a guest.

`spawnables vaults check` reports installed / auth_missing / usable per source, because "the
integration exists" and "the integration is authenticated" are different facts and an agent that
conflates them plans around a capability that is not there.

## what exists, and what is still a spec

asked plainly (nov 2026): did we pair an authenticator app, or build vaultwarden/bitwarden
rails the way 1password plus the guest agent-vault is designed? the answer is no to all three,
and the gap is worth stating so nobody plans around a rail that is not there.

| piece | state | evidence |
| --- | --- | --- |
| totp decoding and code computation | **built** | `twofa.py`: `decode_command`, `extract_totp`, `classify`, `scan_gate`; seeds are referenced as `@@vault:` |
| seed storage in the sealed vault | **built for totp uris** | the same vault path every other secret uses; one seed per identity, never copied to a second guest |
| proton authenticator | **not integrated, by design** | no code; it is the human's copy of the seed. mobile clients public under `protonpass/` (kotlin + swift, gpl-3.0, verified 2026-11-01); desktop source unpublished |
| 1password | **source wired** | `vaults.py` (`op read` / `--otp`), auth is the owner's service-account token; still never signed into a guest |
| agent-vault (infisical) proxy | **spec only** | no `agent_vault` code in `src/` (checked). the design is written, the egress proxy is not |
| vaultwarden | **app + resolve rail** | `catalog/services/vaultwarden.json` (agpl-3.0, port 8222, ready) plus `vaults.py` driving `bw` at that server; provisioning and the owner's one-time login are still manual |
| bitwarden cli | **built** | `vaults.py` speaks `bw` (password + totp + session), and the same source serves vaultwarden |
| proton pass cli | **built** | `vaults.py` drives `pass-cli item view`, reason required |

so the honest ordering of work here: the proxy is the thing that makes a vault useful to a
guest (it is what keeps the secret out of the guest at all), and until it exists, pointing at
vaultwarden would only mean a second place to copy secrets from by hand. the app is ready when
the rail is.

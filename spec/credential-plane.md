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

## what exists, and what is still a spec

asked plainly (nov 2026): did we pair an authenticator app, or build vaultwarden/bitwarden
rails the way 1password plus the guest agent-vault is designed? the answer is no to all three,
and the gap is worth stating so nobody plans around a rail that is not there.

| piece | state | evidence |
| --- | --- | --- |
| totp decoding and code computation | **built** | `twofa.py`: `decode_command`, `extract_totp`, `classify`, `scan_gate`; seeds are referenced as `@@vault:` |
| seed storage in the sealed vault | **built for totp uris** | the same vault path every other secret uses; one seed per identity, never copied to a second guest |
| proton authenticator | **not integrated, by design** | no code; it is the human's copy of the seed. mobile clients public under `protonpass/` (kotlin + swift, gpl-3.0, verified 2026-11-01); desktop source unpublished |
| 1password | **spec only** | `spec/credential-plane.md`; kernel ships an integration, we treat 1password as the owner's vault reached through a broker, never signed into a guest |
| agent-vault (infisical) proxy | **spec only** | no `agent_vault` code in `src/` (checked). the design is written, the egress proxy is not |
| vaultwarden | **provisionable app, no rail** | `catalog/services/vaultwarden.json`, agpl-3.0, port 8222, status ready. its notes now say the credential plane does not point at it yet |
| bitwarden cli / api integration | **not built** | nothing in `src/` speaks `bw` |

so the honest ordering of work here: the proxy is the thing that makes a vault useful to a
guest (it is what keeps the secret out of the guest at all), and until it exists, pointing at
vaultwarden would only mean a second place to copy secrets from by hand. the app is ready when
the rail is.

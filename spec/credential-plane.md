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

correction to keep on file: i could not confirm a bitbucket integration in the list i
read; confirm before repeating it.

## two-factor: the app is not on the critical path

an authenticator app stores an `otpauth://` uri. a code is a computation over that uri,
not a feature of an app. we already decode the qr (`twofa.py`), so the agent's side is:
decode the qr the service shows, seal the uri in the vault, compute codes at use time.
the app choice matters only for the human holding the same seed later. proton
authenticator is a reasonable choice for that, but i could not verify its licence or
export format from the urls i tried (both 404), so nothing here depends on it.

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
- kernel's bitbucket integration unverified; proton authenticator licence unverified.

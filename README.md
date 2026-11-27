# spawnables

one front door, and a part at a time.

```
pip install spawnables
spawnables get durables
```

that is the whole idea: the front door is small and always the same, and each part of the project is
onramped when you want it. the shape is borrowed from `heyphony get signal`, where one command is
the install.

## what `get` does

`spawnables get <part>` prints a plan: what the part is, what it needs, what it refuses, how it
installs, and how it verifies. **dry by default** - nothing is downloaded until you pass `--run`,
because a getter that installs on a typo is a getter nobody runs twice.

```
spawnables list                # the parts, one line each
spawnables get durables        # the plan: install line, verify line, refusals
spawnables get durables --run  # actually install, then verify
spawnables card                # the whole front door as json
```

## the parts

| part | kind | what it is |
|---|---|---|
| `durables` | pypi | durable objects for python: names with mailboxes, v8 isolates expected to die |
| `nesting` | source | containers in a guest, a vm in a guest, and the difference between them |
| `machines` | refused | the control plane itself |

## the rule, said once

**components ship to pypi; the control plane never does.**

a component is a library: you install it, you import it, it does a job in your process. the control
plane provisions machines and holds credentials, so it belongs on a host you run and can audit, not
in site-packages where nobody reads it before it starts. `spawnables get machines` refuses in those
words and gives you the clone instead.

## why a getter is data

each part is a json recipe in `spawnables_cli/getters/`, because the content that matters is the
verify step and the refusal, and both are easier to keep honest as text than as branches:

```json
{
  "name": "durables",
  "kind": "pypi",
  "install": "pip install 'spawnables-durables>=0.1.0'",
  "verify": "durables card",
  "refused": ["a kernel of its own: a v8 isolate is a heap in a process, not a machine"],
  "verified": true
}
```

a getter that reports success without running its verify is a claim rather than a capability, so
`--run` stops at the first non-zero exit and says which step failed.

## install name vs import name

the distribution is `spawnables`, the import is `spawnables_cli`, and the script is `spawnables`.
that split is deliberate: the control plane's own package is also called `spawnables`, so a repo
developer with both would otherwise have two things claiming one import path.

## honest gaps

- **two getters, one published.** `durables` installs from the index; `nesting` installs from source
  because that branch has no package metadata yet.
- **no lockfile, no version pinning beyond the recipe.** a getter is an onramp, not a resolver.
- **no uninstall.** `pip uninstall spawnables-durables` is the answer, and pretending otherwise
  would be a worse one.

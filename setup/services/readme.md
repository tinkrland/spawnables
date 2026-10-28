# services

self-hosted docker instances you connect before you run the machine -
the manifest's services list, the runner does the rest:

- at provisioning: docker is installed and enabled, the official
  compose is fetched at the pinned tag (penpot 2.18.5 first), and the
  stack comes up. the agent never hand-rolls self-hosting.
- on every boot: systemctl enable plus the compose restart policy bring
  the stack back by itself; no agent involvement.
- data lives in compose volumes, so pause/freeze/thaw carries the
  service and its data with the machine.
- local-first: a service answers on localhost; exposing it to the
  network is the owner's explicit choice, never a default. linux guests
  only, ~2gb ram floor on the card.

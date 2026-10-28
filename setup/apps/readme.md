# apps

apps are [recipes](../../catalog/recipes) ordered on the manifest and
installed at provisioning:

- native orders key on distro family (debian serves ubuntu, mint, pop;
  windows keys winget; macos keys brew casks), so mint installs obsidian
  the same hour ubuntu does.
- pwa orders go through one shared handler keyed by browser: figma,
  netflix and friends install as app windows with no per-app ceremony.
- every recipe carries its own verify step - a card goes ready only
  when each ordered app passes; a failure surfaces as a named missing
  app, not a timeout.
- pin tells the provisioner where the app surfaces (menu, dash, start
  menu, dock) and availability grays out what an os cannot run.

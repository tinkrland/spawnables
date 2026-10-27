# order form spec

the order form is one data model with two sides: a **machine order** (what the user wants) and four **catalogs** (what exists). the form renders from the catalogs, validates the order against them, and the provisioner replays the order verbatim. the order is stored with the machine forever.

## objects

| object | schema | one per | what it answers |
|---|---|---|---|
| base image | [base-image.schema.json](schemas/base-image.schema.json) | os/distro/desktop combo | what can boot |
| path tool | [path-tool.schema.json](schemas/path-tool.schema.json) | cli tool | what can go on PATH |
| app recipe | [recipe.schema.json](schemas/recipe.schema.json) | app | what apps exist and how they install |
| rice | [rice.schema.json](schemas/rice.schema.json) | skin bundle | what a machine can wear |
| machine order | [machine-order.schema.json](schemas/machine-order.schema.json) | user request | what one user asked for |

## chained pickers

the form narrows left to right; each catalog carries the matrix that grays out impossible next steps:

```
os -> distro -> desktop env -> (tools, apps, rice)
```

- os comes from base images (`linux`, `windows`, `macos`).
- distro comes from base images for that os. windows and macos orders skip this picker.
- desktop env comes from base images for that distro (mint means cinnamon, fedora means gnome or a spin, arch means you pick).
- apps filter by the recipe availability matrix (os x order type) and, for native orders, by distro family.
- rice filters by compatible desktops.

a submit is rejected if any ordered item fails its matrix. the form should make invalid states unselectable; the api re-validates anyway.

## machine order

```json
{
  "id": "mo_8f3k",
  "name": "evie-desk",
  "base_image": "mint-22-cinnamon",
  "arch": "x86_64",
  "size": { "vcpus": 4, "ram_mb": 8192, "disk_gb": 80 },
  "timezone": "asia/kolkata",
  "locale": "en-in",
  "path_tools": ["git", "node", "python"],
  "apps": [
    { "recipe_id": "kicad", "order_type": "native" },
    { "recipe_id": "figma", "order_type": "pwa" },
    { "recipe_id": "netflix", "order_type": "pwa" }
  ],
  "rice": { "rice_id": "catppuccin-mocha-cinnamon", "version": "1.2.0" },
  "agent_bridge": { "expose": ["mcp", "ssh", "vnc"], "egress": "on" },
  "rebuild_on_thaw": false
}
```

`path_tools` and `apps` are separate catalogs on purpose: things the agent calls in a shell vs things pinned to the launcher/dock.

## base image

```json
{
  "id": "mint-22-cinnamon",
  "os": "linux",
  "distro": "linuxmint",
  "distro_family": "debian",
  "desktop_env": "cinnamon",
  "version": "22",
  "arch": ["x86_64"],
  "package_manager": "apt",
  "image": "images/mint-22-cinnamon.qcow2",
  "default_browser": "brave"
}
```

the distro catalog is a set of maintained base images, nothing more exotic. `distro_family` is the join key for recipes and path tools: a `debian` family recipe serves ubuntu, mint, pop. windows images key `distro_family: "windows"`, macos images `distro_family: "macos"`, and both go straight from the os picker to desktop env.

## path tool

```json
{
  "id": "node",
  "installs": {
    "debian": {
      "steps": ["curl -fsSL https://deb.nodesource.com/setup_22.x | bash -", "apt install -y nodejs"],
      "verify": "node --version"
    },
    "fedora": { "steps": ["dnf install -y nodejs"], "verify": "node --version" },
    "arch": { "steps": ["pacman -S --noconfirm nodejs"], "verify": "node --version" },
    "windows": { "steps": ["winget install -e --id OpenJS.NodeJS"], "verify": "node --version" }
  },
  "disk_mb_est": 220
}
```

## app recipe

```json
{
  "recipe_id": "kicad",
  "category": "engineering",
  "orders": {
    "native": {
      "debian": { "manager": "apt", "steps": ["apt install -y kicad"], "verify": "kicad-cli version" },
      "fedora": { "manager": "dnf", "steps": ["dnf install -y kicad"], "verify": "kicad-cli version" },
      "arch": { "manager": "pacman", "steps": ["pacman -S --noconfirm kicad"], "verify": "kicad-cli version" },
      "windows": { "manager": "winget", "steps": ["winget install -e --id KiCad.KiCad"], "verify": "kicad-cli version" },
      "macos": { "manager": "brew-cask", "steps": ["brew install --cask kicad"], "verify": "ls /applications/kicad.app" }
    }
  },
  "availability": { "linux": ["native"], "windows": ["native"], "macos": ["native"] },
  "pin": { "cinnamon": "menu", "gnome": "dash", "windows": "startmenu", "macos": "dock" },
  "egress_required": true,
  "disk_mb_est": 1400
}
```

rules:

- native install steps key on **distro family** (debian serves ubuntu/mint/pop), never on a single distro.
- pwa orders do not live in each recipe. one shared pwa handler keyed by browser takes a url + browser hint; recipes only declare the url when the app is installable that way. this keeps the registry crowdsourceable.

```json
{
  "recipe_id": "figma",
  "category": "design",
  "orders": { "pwa": { "url": "https://figma.com" } },
  "availability": { "linux": ["pwa"], "windows": ["pwa"], "macos": ["pwa"] }
}
```

- `verify` is the acceptance test. a card goes ready only when every ordered recipe passes verify; failures surface as a named missing app, not a timeout.
- `pin` tells the provisioner how to surface the app in the chosen desktop (menu entry, dash, start menu, dock). a missing pin is a registry gap, not a provision failure: the app installs fine, it just doesn't show.
- `availability` is the graying-out matrix. office is native on windows/macos only, netflix native on windows only, figma is pwa everywhere, kicad is native everywhere.

## rice

```json
{
  "rice_id": "catppuccin-mocha-cinnamon",
  "version": "1.2.0",
  "compatible_desktops": ["cinnamon"],
  "theme_engine": "gtk",
  "assets": {
    "wallpaper": "assets/wall.png",
    "gtk_theme": "assets/catppuccin-mocha.zip",
    "icons": "assets/catppuccin-icons.zip"
  },
  "apply": {
    "steps": [
      "unzip assets/catppuccin-mocha.zip -d ~/.themes",
      "gsettings set org.cinnamon.desktop.interface gtk-theme 'catppuccin-mocha-standard'",
      "gsettings set org.cinnamon.desktop.background picture-uri 'file://~/wall.png'"
    ]
  },
  "source": "github:catppuccin/catppuccin"
}
```

rices are desktop-specific by nature (a hyprland rice won't skin cinnamon), so `compatible_desktops` gates the picker. upload formats: tarball or a git url, dotfiles style. the rice applies at provision time, after app verify, before the fresh-point snapshot: a riced machine is itself freeze-able and exportable.

## versioning

an order pins what it ordered:

- every recipe and rice resolves to a version + sha256 digest at order time.
- the stored order keeps those pins, so thaw-with-rebuild and re-provision replay identically.
- registry updates never mutate an existing machine; they only affect new orders.

## provision pipeline

| stage | does | emits |
|---|---|---|
| boot | create the microvm from the base image | `provision.boot` |
| locale | set timezone + locale | `provision.locale` |
| tools | install + verify each path tool | `provision.tools` (one per tool) |
| apps | install + verify each ordered app, pin to desktop | `provision.app` (one per app) |
| rice | apply the skin bundle | `provision.rice` |
| snapshot | fresh-point snapshot | `provision.ready` |

progress streams over `GET /api/machines/:id/events`; states and verbs live in the [card lifecycle spec](card-lifecycle.md).

## sizing

the form exposes presets plus custom sliders for vcpus, memory, and disk, with per-guest-os limits enforced in the form (never discovered at provision time):

- linux (celesto): memory and disk adjustable at create time; vcpus is pinned at 2 in current celesto. template-level caps exist (e.g. desktop disks); the form carries them as slider bounds.
- windows (celesto): memory and disk adjustable at create time.
- macos (celesto): fixed 4 vcpu / 8 gb / 80 gb; custom sizes not enabled yet, so the form hides the sliders.
- android / ios: per backend adapter; bounds pinned when each adapter lands.

celesto has no live resize. changing size is a **rebuild from the manifest**, which manifest replay already makes cheap; the card presents resize as a rebuild, not an in-place stretch. on byo cloud infra, size maps to instance type at provision time.

## extended guests: android and ios

not celesto-backed. each needs a spawnables backend adapter, and the card verbs degrade per backend:

- **android**, three real routes:
  - android-x86 in qemu: a real VM, so pause works and freeze is plausible (qemu snapshots) but unverified. recipes key on an `android` family whose install steps are `adb install` commands; verify via `pm list packages`. gui streams to the card over scrcpy (ws-scrcpy).
  - redroid (remote-android): containers, GPU-enabled, scales easiest, but no qemu snapshots, so no freeze.
  - cuttlefish: google's virtual android device, aosp images, heaviest setup; parked until someone asks.
- **ios**: the vphone ecosystem (vphone-cli, 16k stars) runs virtual iphones on apple silicon macs; vphone-linux ports it to linux qemu on apple's vresearch101 machine type. research-grade, image sourcing is legally gated, so ios is an experimental bring-your-own-image tier with the license question disclosed in the form.

## windows versions and microsoft apps

windows version is a base image concern: celesto builds the image from whatever iso you feed it (`celesto windows build-image`), so `win11-24h2` and `win10-22h2` are simply two base-image entries in the catalog, version pinned like everything else. microsoft apps are ordinary winget recipes: clipchamp ships inbox on windows 11 (winget id `clipchamp.clipchamp` covers the rest of the suite cases), and the availability matrix gates them the same as any app.

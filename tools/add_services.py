"""write the new self-hosted service entries into catalog/services."""
import json
import pathlib

OUT = pathlib.Path("catalog/services")
OUT.mkdir(parents=True, exist_ok=True)

DOCKER = {"label": "docker", "cmd": "apt-get update && apt-get install -y docker.io docker-compose-v2"}
BOOT = {"label": "boot", "cmd": "systemctl enable --now docker"}


def single(sid, category, license, port, ram, image, volume, notes, verify=None, version="image 'latest' - pin at first provisioning"):
    return {
        "service_id": sid,
        "category": category,
        "version": version,
        "license": license,
        "status": "ready",
        "os": ["linux"],
        "port": port,
        "ram_mb_floor": ram,
        "steps": [
            DOCKER,
            BOOT,
            {"label": "fetch", "cmd": f"docker pull {image}"},
            {"label": "up", "cmd": f"docker rm -f spawnables-{sid} >/dev/null 2>&1; docker run -d --restart unless-stopped --name spawnables-{sid} -p {port}:{port} -v /opt/spawnables-services/{sid}:{volume} {image}"},
        ],
        "verify": verify or f"curl -sf http://localhost:{port} -o /dev/null || curl -sf http://localhost:{port}/ -o /dev/null",
        "notes": notes,
    }


SERVICES = [
    single(
        "vaultwarden", "secrets", "agpl-3.0 (oss)", 8222, 512,
        "vaultwarden/server:latest", "/data",
        "bitwarden-compatible server in one container (rust, no bitwarden cloud account). this is the vault the credential plane points at, and since nov 2026 the resolve rail exists: spawnables/vaults.py drives the same `bw` cli at SPAWNABLES_VAULTWARDEN_URL (this container, port 8222), so an agent can ask for one value or one totp code instead of holding anything. what is still missing is provisioning plus the owner's one-time `bw config server` + login on the control plane. signups are off by default in the image, so enabling an account stays an explicit step on the owner's card.",
        verify="curl -sf http://localhost:8222/alive -o /dev/null || curl -sf http://localhost:8222 -o /dev/null",
    ),
    single(
        "excalidraw", "design", "mit (oss)", 8080, 256,
        "excalidraw/excalidraw:latest", "/data",
        "the whiteboard, self-hosted, no account and no telemetry. honest limit: collab rooms need a separate excalidraw-room container, so this is single-user drawing on localhost until that is added. version tag is 'latest' today and the card says so rather than pretending a pin.",
    ),
    single(
        "code-server", "dev", "mit (oss)", 8080, 768,
        "codercom/code-server:latest", "/home/coder/.local",
        "vs code in the guest's browser at localhost:8080, which is what we actually ship when someone says 'vscode': microsoft's own build is mit-licensed but its marketplace terms are not, so the oss editor (openvscode-server or code-server) is the honest default and the card says which one it is.",
    ),
    single(
        "langflow", "automation", "mit (oss)", 7860, 1024,
        "langflowai/langflow:latest", "/app/data",
        "visual builder for llm flows (python fastapi under the hood). runs with sqlite by default so a single container is honest here; pointing it at postgres is a compose change, not a promise. this is the low-code lane next to n8n's integration lane.",
    ),
    single(
        "n8n", "automation", "fair-code: sustainable use license, NOT osi open source", 5678, 768,
        "docker.n8n.io/n8nio/n8n:latest", "/home/node/.n8n",
        "workflow automation, 400+ integrations, self-hosted. the license is the honest part: n8n is fair-code (sustainable use license), source-available but not osi-approved, and reselling it as a service is restricted. fine for an owner-run machine, worth knowing before anyone builds a product on it. workflows and credentials live in the volume, so freeze/thaw carries them.",
    ),
    single(
        "observable-framework", "data", "isc (oss) - the hosted notebook platform is not", 8081, 512,
        "node:22-alpine", "/app",
        "observable's data apps as static files: the framework is isc and self-hostable, while the observablehq.com notebook platform is a commercial service. so this entry is the framework served from the guest at localhost:8081, and it deliberately does not pretend to be the platform. needs a build step in /opt/spawnables-services/observable before it serves anything.",
        version="node 22 image, framework version from the project's package.json",
    ),
    {
        "service_id": "affine",
        "category": "design",
        "version": "unpinned - official compose to be pinned at first provisioning",
        "license": "mit core with a commercial enterprise edition (license file is mixed, not osi-clean)",
        "status": "planned",
        "os": ["linux"],
        "port": 3010,
        "ram_mb_floor": 2048,
        "steps": [],
        "verify": "curl -sf http://localhost:3010 -o /dev/null",
        "notes": "the notion-plus-miro alternative: docs, whiteboards and databases in one workspace. multi-container (graphql server, postgres, redis), so it is planned rather than ready: the honest blocker is that we have not pinned upstream's compose file yet, and a half-fetched compose is worse than an absent service. same doctrine as penpot: local-first on localhost:3010, volumes survive freeze.",
    },
    {
        "service_id": "appflowy",
        "category": "notes",
        "version": "unpinned - official compose to be pinned at first provisioning",
        "license": "agpl-3.0 (oss)",
        "status": "planned",
        "os": ["linux"],
        "port": 8080,
        "ram_mb_floor": 3072,
        "steps": [],
        "verify": "curl -sf http://localhost:8080 -o /dev/null",
        "notes": "notion-shaped workspace you own outright (flutter + rust). explicitly the answer to notion dependence: databases, kanban, docs, local-first sync. multi-container (postgres, redis, minio, gotrue), hence planned. agpl means improvements stay open, which is the point.",
    },
    {
        "service_id": "karakeep",
        "category": "knowledge",
        "version": "unpinned - official compose to be pinned at first provisioning",
        "license": "agpl-3.0 (oss)",
        "status": "planned",
        "os": ["linux"],
        "port": 3000,
        "ram_mb_floor": 2048,
        "steps": [],
        "verify": "curl -sf http://localhost:3000 -o /dev/null",
        "notes": "bookmark-everything (formerly hoarder): links, notes, images, auto-tagging. multi-container because it wants meilisearch for search and headless chrome for page capture, which is also why it belongs on a machine with room. agpl-3.0.",
    },
    {
        "service_id": "deepnotes",
        "category": "notes",
        "version": "unpinned - official compose to be pinned at first provisioning",
        "license": "agpl-3.0 (oss)",
        "status": "planned",
        "os": ["linux"],
        "port": 3000,
        "ram_mb_floor": 2048,
        "steps": [],
        "verify": "curl -sf http://localhost:3000 -o /dev/null",
        "notes": "end-to-end encrypted notes with an infinite canvas (offline-first, sync when it can reach the server). agpl-3.0. multi-container (server, redis, mongo), hence planned. the e2ee part is a real fit for owner data on a machine somebody else's kernel is running.",
    },
    {
        "service_id": "kinopio",
        "category": "design",
        "version": "n/a",
        "license": "client source-available (no spdx id); server is hosted-only",
        "status": "not-offered",
        "os": ["linux"],
        "port": None,
        "ram_mb_floor": 0,
        "steps": [],
        "verify": "true",
        "notes": "spatial thinking tool, genuinely nice, and we do not ship it: the client is on github without a clean osi license and the server is a hosted product, so 'self-hosted kinopio' would be a costume. it stays reachable the normal way, from a browser in the guest, against their service. recorded here so the absence is a decision with a reason instead of an oversight.",
    },
]

for svc in SERVICES:
    (OUT / f"{svc['service_id']}.json").write_text(json.dumps(svc, indent=2) + "\n")
print("wrote", len(SERVICES), "services:", ", ".join(s["service_id"] for s in SERVICES))

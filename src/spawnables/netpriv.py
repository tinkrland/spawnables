"""network & privacy: section 03 of the order form.

the seven toggles from the design reference: private dns (nextdns), proxy ip
pools + dedicated ip (kernel / tailscale), vpn exit (proton / windscribe, open-source tunnels and kill switches), mac spoofing, browser
dnt + anti-fingerprinting, kill switch, and matching vm specs to the vpn
exit. every toggle splits into guest-side steps (run in the vm during
provisioning) and host-side directives (applied by the host runner at the
fabric level: qemu nic, nftables, routing). secrets never ride in the
order: byo vpn configs live in a vault and the order stores references.
"""
import json

DEFAULTS = {
    "private_dns": False,       # off in the design reference
    "proxy": False,             # off
    "vpn": False,               # on in the reference, but byo config required
    "mac_spoof": True,          # on
    "browser_hardening": True,  # on
    # kill switch guards a tunnel; the form pre-checks it the moment a
    # tunnel goes on, and validation rejects it without one
    "kill_switch": False,
    "match_specs_to_vpn": False,  # off
    # exit_geo declares the country/city of the active tunnel exit; the
    # coherence layer reads it to keep timezone + language believable
    "exit_geo": {},
    # dedicated-ip provider when the pool is 'dedicated' (kernel|tailscale)
    "dedicated_ip_provider": None,
}

# providers, per the owner's verdicts. all auth goes through vault
# references (@@vault:ref@@), never the order.
# - vpn lane: proton + windscribe + mullvad. all three are open
#   source and battle-tested, and all three hand out wireguard
#   profiles: proton from the account (or the open-source
#   protonvpn-cli api path), windscribe via its config generator /
#   official rest api, mullvad from its numbered account (single-hop
#   or multihop). configs land in the vault; the guest gets wg-quick.
# - dedicated ip lane: kernel or tailscale. kernel (kernel.sh, oss
#   reference repo github.com/kernel/kernel-images) is the proxy
#   infrastructure borrow; tailscale gives a stable exit node on a
#   byo tailnet. tailscale left the vpn lane by this verdict.
# - proxy pools (shared): residential reads as a home connection,
#   commercial as business infrastructure.
VPN_PROVIDERS = ("proton", "windscribe", "mullvad")
DEDICATED_IP_PROVIDERS = ("kernel", "tailscale")
PROXY_POOLS = ("residential", "commercial", "dedicated")

# nextdns integration lane: api.nextdns.io exposes profile management
# (create/update/delete profiles) with an api key. the runner provisions
# ONE nextdns profile per machine card, vault-referenced api key; the
# order stores only the profile id it gets back.
NEXTDNS_API = "https://api.nextdns.io"

# reference: kernel/kernel-images (open source) does browser anti-fingerprint
# infrastructure for agents; our hardening steps cover the same surface for
# the browsers we provision, keyed on the base image's default browser.


def normalize(network):
    """merge user toggles over the defaults; returns the full section."""
    net = dict(DEFAULTS)
    if network:
        net.update({k: v for k, v in network.items() if k in DEFAULTS})
        for k in ("private_dns_profile", "proxy_pool", "vpn_provider", "vpn_config_ref",
                  "dedicated_ip_provider"):
            if network.get(k):
                net[k] = network[k]
    return net


def validate_network(net, order):
    errors = []
    if net["private_dns"] and not net.get("private_dns_profile"):
        errors.append("private dns is on but no nextdns profile id is set")
    if net["proxy"] and net.get("proxy_pool") not in PROXY_POOLS:
        errors.append(f"proxy is on but pool is unset; pick one of {PROXY_POOLS}")
    if net.get("proxy_pool") == "dedicated":
        if net.get("dedicated_ip_provider") not in DEDICATED_IP_PROVIDERS:
            errors.append(f"a dedicated ip needs a provider; pick one of {DEDICATED_IP_PROVIDERS}")
        if net.get("dedicated_ip_provider") == "tailscale" and not net.get("vpn_config_ref"):
            errors.append("tailscale dedicated ip needs a vault auth key reference")
    if net["vpn"]:
        if net.get("vpn_provider") not in VPN_PROVIDERS:
            errors.append(f"vpn is on but provider is unset; pick one of {VPN_PROVIDERS}")
        if not net.get("vpn_config_ref"):
            errors.append("vpn is on but no vault config reference is set "
                          "(configs live in the vault; the order stores only a reference)")
    if net["kill_switch"] and not (net["vpn"] or net["proxy"]):
        errors.append("kill switch guards the vpn or proxy tunnel; turn one on first")
    if net["match_specs_to_vpn"] and not net["vpn"]:
        errors.append("match specs to vpn exit needs the vpn on")
    return errors


def host_directives(net):
    """what the host runner applies at the fabric level, before/around boot."""
    return {
        "mac_spoof": net["mac_spoof"],  # qemu nic mac randomized per spawn
        "kill_switch": net["kill_switch"],  # nftables: only the tunnel iface leaves
        "proxy_pool": net["proxy_pool"] if net["proxy"] else None,
        "dedicated_ip_provider": (net.get("dedicated_ip_provider")
                                  if net.get("proxy_pool") == "dedicated" else None),
        "vpn_exit": net["vpn_provider"] if net["vpn"] else None,
        # note: celesto passthrough for custom qemu args is unverified; the
        # runner owns the fabric until that lands.
    }


def guest_steps(net, os_name, browser):
    """commands run inside the vm during provisioning. linux today."""
    steps = []
    if os_name != "linux":
        return steps  # guest-side steps are linux-first; host directives still apply
    if net["vpn"]:
        # proton + windscribe: both hand out wireguard profiles (proton
        # from the account, windscribe via its config generator); both
        # clients are open source with their own kill switches on top
        # of our nftables one. profiles live in the vault.
        ref = net["vpn_config_ref"]
        steps.append((f"vpn.{net['vpn_provider']}",
                      f"apt install -y wireguard && install -m 600 @@vault:{ref}@@ /etc/wireguard/wg0.conf "
                      f"&& systemctl enable --now wg-quick@wg0"))
    if net["proxy"] and net.get("proxy_pool") == "dedicated" and \
            net.get("dedicated_ip_provider") == "tailscale":
        # a stable exit of your own on a byo tailnet
        steps.append(("dedicated.tailscale",
                      f"curl -fsSL https://tailscale.com/install.sh | sh && "
                      f"tailscale up --auth-key=@@vault:{net['vpn_config_ref']}@@ --exit-node=@@vault:ts-exit-node@@"))
    # kernel dedicated ip is applied host-side: the runner wires the
    # kernel proxy infra at the fabric level (browser egress + machine
    # egress), api token in the vault
    if net["match_specs_to_vpn"]:
        # the vm syncs to the declared exit's story: clock, timezone,
        # locale, date orientation, units, currency - so the real
        # machine's settings never leak through metadata. derived from
        # the declared exit (deterministic), then verified live through
        # the tunnel so a misdeclared exit fails loudly.
        from .coherence import exit_story, expected_timezone, tz_key
        tz = tz_key(expected_timezone(net) or "") or ""
        story = exit_story(net)
        steps.append(("specs.sync.clock",
                      f"timedatectl set-timezone {tz}"))
        if story:
            loc = story["locale"]
            steps.append(("specs.sync.locale",
                          f"locale-gen {loc} >/dev/null 2>&1; "
                          f"localectl set-locale LANG={loc} LC_TIME={loc} "
                          f"LC_MONETARY={loc} LC_MEASUREMENT={loc} "
                          f"LC_NUMERIC={loc}"))
        steps.append(("specs.sync.verify",
                      f'test "$(curl -fsS --max-time 10 '
                      f'https://ipinfo.io/timezone)" = "{tz}" '
                      f'|| (echo "egress story disagrees with the declared '
                      f'exit" && false)'))
    if net["private_dns"]:
        profile = net["private_dns_profile"]
        steps.append(("dns.nextdns",
                      f"curl -sL https://nextdns.io/install | sh && "
                      f"nextdns install -config {profile}"))
    if net["browser_hardening"]:
        if browser == "firefox":
            policy = {
                "DisableTelemetry": True,
                "Preferences": {
                    "privacy.resistFingerprinting": True,
                    "privacy.donottrackheader.enabled": True,
                },
            }
            steps.append(("browser.hardening.firefox",
                          f"mkdir -p /etc/firefox/policies && printf '%s' "
                          f"'{json.dumps(policy)}' > /etc/firefox/policies/policies.json"))
        else:
            # brave: shields randomize canvas/webgl/audio signals by default;
            # managed policy pins the rest and keeps rewards/vpn promos off
            policy = {"BraveRewardsDisabled": True, "BraveVPNDisabled": True}
            steps.append(("browser.hardening.brave",
                          f"mkdir -p /etc/brave/policies/managed && printf '%s' "
                          f"'{json.dumps(policy)}' > /etc/brave/policies/managed/spawnables.json"))
    if net["kill_switch"] and net["vpn"]:
        # guest-side belt on top of the host-side suspenders: after the tunnel
        # is up, only lo, the tunnel iface, and established flows leave
        iface = ("tailscale0" if net.get("dedicated_ip_provider") == "tailscale"
                 else "wg0")
        steps.append(("killswitch.nft",
                      f"nft add table inet ks && nft 'add chain inet ks out {{ type filter hook output "
                      f"priority 0 ; policy drop ; }}' && nft add rule inet ks out oif lo accept && "
                      f"nft add rule inet ks out oif {iface} accept && "
                      f"nft add rule inet ks out ct state established,related accept'"))
    return steps

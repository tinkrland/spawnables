"""network & privacy: section 03 of the order form.

the seven toggles from the design reference: private dns (nextdns), proxy ip
pools, byo vpn exit (tailscale / proton / wireguard), mac spoofing, browser
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
}

VPN_PROVIDERS = ("tailscale", "proton", "wireguard")
PROXY_POOLS = ("residential", "commercial")

# reference: kernel/kernel-images (open source) does browser anti-fingerprint
# infrastructure for agents; our hardening steps cover the same surface for
# the browsers we provision, keyed on the base image's default browser.


def normalize(network):
    """merge user toggles over the defaults; returns the full section."""
    net = dict(DEFAULTS)
    if network:
        net.update({k: v for k, v in network.items() if k in DEFAULTS})
        for k in ("private_dns_profile", "proxy_pool", "vpn_provider", "vpn_config_ref"):
            if network.get(k):
                net[k] = network[k]
    return net


def validate_network(net, order):
    errors = []
    if net["private_dns"] and not net.get("private_dns_profile"):
        errors.append("private dns is on but no nextdns profile id is set")
    if net["proxy"] and net.get("proxy_pool") not in PROXY_POOLS:
        errors.append(f"proxy is on but pool is unset; pick one of {PROXY_POOLS}")
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
        provider = net["vpn_provider"]
        ref = net["vpn_config_ref"]
        if provider == "tailscale":
            steps.append(("vpn.tailscale",
                          f"curl -fsSL https://tailscale.com/install.sh | sh && "
                          f"tailscale up --auth-key=@@vault:{ref}@@"))
        elif provider == "proton":
            # proton hands out wireguard profiles; they ride through the same lane
            steps.append(("vpn.proton",
                          f"apt install -y wireguard && install -m 600 @@vault:{ref}@@ /etc/wireguard/wg0.conf "
                          f"&& systemctl enable --now wg-quick@wg0"))
        else:
            steps.append(("vpn.wireguard",
                          f"apt install -y wireguard && install -m 600 @@vault:{ref}@@ /etc/wireguard/wg0.conf "
                          f"&& systemctl enable --now wg-quick@wg0"))
    if net["match_specs_to_vpn"]:
        # the vm reads its own egress story through the tunnel and syncs to it,
        # so the real timezone never leaks through metadata
        steps.append(("specs.sync",
                      "timedatectl set-timezone $(curl -s https://ipinfo.io/timezone)"))
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
        iface = "tailscale0" if net["vpn_provider"] == "tailscale" else "wg0"
        steps.append(("killswitch.nft",
                      f"nft add table inet ks && nft 'add chain inet ks out {{ type filter hook output "
                      f"priority 0 ; policy drop ; }}' && nft add rule inet ks out oif lo accept && "
                      f"nft add rule inet ks out oif {iface} accept && "
                      f"nft add rule inet ks out ct state established,related accept'"))
    return steps

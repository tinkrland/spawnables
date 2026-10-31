"""the mobile tells the coherence layer could not see.

coherence checks the story a phone TELLS (clock, language, screen, camera).
this checks the story the phone cannot help telling, because it comes from
hardware: sensor noise, the gpu string a browser reports, the build
properties, the carrier identity, and whether an attestation claim is
possible at all.

severity follows the coherence rule: 'fail' stops the flow, 'warn' proceeds
and puts the disagreement on the card. the shape is the same four-tuple so
mobile_tells() output can sit beside mobile_coherence() output.
"""

SOFTWARE_GPUS = ("swiftshader", "llvmpipe", "softpipe", "virgl", "mesa offscreen")

# a persona's chip family has to agree with the gpu the browser reports.
# snapdragon phones say adreno, exynos and tensor say mali (or xclipse on
# amd-partnered exynos), and a mismatch is one of the oldest emulator tells.
GPU_FAMILIES = {
    "pixel": ("mali", "adreno"),
    "google": ("mali",),
    "samsung": ("mali", "xclipse", "adreno"),
}


def gpu_tells(device):
    """what webgl says, read against what the phone claims to be."""
    issues = []
    renderer = (device.get("webgl_renderer") or "").lower()
    if not renderer:
        return issues
    if any(soft in renderer for soft in SOFTWARE_GPUS):
        issues.append(("gpu", renderer, "hardware gpu", "fail",
                       "a software renderer is a headless browser, not a phone"))
        return issues
    brand = (device.get("brand") or device.get("persona") or "").lower()
    allowed = GPU_FAMILIES.get(brand)
    if allowed and not any(fam in renderer for fam in allowed):
        issues.append(("gpu", " / ".join(allowed), renderer, "fail",
                       "gpu family disagrees with the model: the chip is the tell"))
    return issues


def sensor_tells(device):
    """sensors are the hardest thing to fake and the cheapest to check.

    a phone has an accelerometer and a gyro. synthetic readings are flat,
    quantised, or identical across axes, and low sample rates give them away
    before any statistical test would.
    """
    issues = []
    sensors = device.get("sensors") or {}
    if not sensors:
        return issues
    accel, gyro = sensors.get("accelerometer"), sensors.get("gyroscope")
    if accel is False:
        issues.append(("sensors", "accelerometer", "absent", "fail",
                       "a phone with no accelerometer is an emulator"))
    if gyro is False and accel:
        issues.append(("sensors", "gyroscope", "absent", "warn",
                       "accel without gyro is unusual on a real handset"))
    hz = sensors.get("sampling_hz")
    if isinstance(hz, (int, float)):
        if hz <= 0:
            issues.append(("sensors", "sampling_hz", hz, "fail",
                           "a sensor that never samples did not feel anything"))
        elif hz in (50, 100, 200) and sensors.get("noise_floor") == 0:
            issues.append(("sensors", "sampling_hz", hz, "fail",
                           "a fixed rate with a zero noise floor is generated data"))
        elif hz < 20:
            issues.append(("sensors", "sampling_hz", hz, "warn",
                           "below any handset's default rate, which looks synthetic"))
    if sensors.get("identical_axes") is True:
        issues.append(("sensors", "axes", "identical", "fail",
                       "x, y and z equal on every sample is a filled array"))
    return issues


# android's release dates, so a patch level older than the os it ships with
# is provably impossible rather than merely suspicious
ANDROID_RELEASED = {9: "2018-08", 10: "2019-09", 11: "2020-09", 12: "2021-10",
                    13: "2022-08", 14: "2023-10", 15: "2024-10"}


def build_props_tells(device):
    """the build the guest reports, checked for things a retail phone never says."""
    issues = []
    props = device.get("build") or {}
    tags = (props.get("tags") or "").lower()
    if props.get("debuggable") is True:
        issues.append(("build", "ro.debuggable", "1", "fail",
                       "no retail handset ships debuggable"))
    if "test-keys" in tags:
        issues.append(("build", "ro.build.tags", tags, "fail",
                       "test-keys is an engineering build, and every matcher knows it"))
    if props.get("security_patch") and device.get("api_level"):
        released = ANDROID_RELEASED.get(int(device.get("api_level") or 0))
        patch = str(props.get("security_patch"))
        if released and patch < released:
            issues.append(("build", released, patch, "fail",
                           "security patch predates the android version it ships with"))
    model, brand = (props.get("model") or ""), (props.get("brand") or "")
    device_name = props.get("device") or ""
    if device_name and model:
        stem = "".join(ch for ch in device_name.lower() if ch.isalnum())
        if stem and stem not in "".join(ch for ch in model.lower() if ch.isalnum()):
            issues.append(("build", "device in model", f"{device_name} vs {model}", "warn",
                           "build device name and model disagree"))
    if brand and device.get("brand") and brand.lower() != str(device.get("brand")).lower():
        issues.append(("build", "brand", f"{brand} vs {device.get('brand')}", "fail",
                       "the build claims a different brand than the card does"))
    return issues


def sim_carrier_tells(device, net=None):
    """a sim and a network that disagree about where they are is the oldest tell."""
    issues = []
    net = net or {}
    sim = device.get("sim") or {}
    if sim.get("present") is False and (device.get("network_kind") or "") in ("mobile", "cellular"):
        issues.append(("sim", "sim present", False, "fail",
                       "claiming a cellular exit with no sim is the modem-less lie"))
        return issues
    sim_country = (sim.get("country_iso") or "").upper()
    net_country = ((net.get("exit_geo") or {}).get("country") or "").upper()
    if sim_country and net_country and sim_country != net_country:
        issues.append(("sim", sim_country, net_country, "fail",
                       "sim country and network country disagree: a roaming shape no handset in this story makes"))
    if sim.get("present") and not (sim.get("mcc") and sim.get("carrier")):
        issues.append(("sim", "mcc/carrier", "missing", "warn",
                       "a present sim with no operator identity will not attach"))
    return issues


def attestation_reality(device):
    """whether this guest can make an attestation claim, and what to say when it cannot.

    play integrity and devicecheck answer 'is this a genuine device', which is
    the exact question an emulator answers wrongly. so the only honest claim
    is the one the hardware can back: none, unless the guest is a real handset.
    """
    kind = (device.get("kind") or "").lower()
    hardware = kind in ("physical", "device-farm")
    return {
        "available": hardware,
        "mechanism": "play integrity / devicecheck" if hardware else None,
        "why": ("a real handset can attest" if hardware else
                "no emulated or containerised guest passes device attestation: "
                "the verdict is computed from hardware keys, so the card must never claim it"),
    }


def mobile_tells(device, net=None):
    """every mobile tell, in the coherence shape, plus the attestation verdict."""
    issues = []
    issues += sensor_tells(device)
    issues += gpu_tells(device)
    issues += build_props_tells(device)
    issues += sim_carrier_tells(device, net)
    verdict = attestation_reality(device)
    if not verdict["available"] and device.get("claims_attestation"):
        issues.append(("attestation", "possible", "claimed", "fail", verdict["why"]))
    return issues


def mobile_tells_block(device, net=None):
    """true when something hardware-level says this guest cannot play the phone."""
    return any(issue[3] == "fail" for issue in mobile_tells(device, net))

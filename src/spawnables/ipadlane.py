"""the ipad lane's 'get anyway' action.

when an agent on the macos apple-silicon machine hits an app-store
entry that reads unavailable on this mac (the developer opted out of
the mac), the card shows a 'get anyway' button beside it. the button
does NOT fetch the app - opting out means there is no legit download
to get - it automates the honest remainder:

1. the control plane mints a handoff request for the decrypted ipa
   (ipa-<bundle> in the vault lane); the owner supplies it, we never
   download apps we have no rights to.
2. until the ipa lands the action sits in 'waiting-for-ipa' - the card
   says so, it never pretends.
3. once the ipa is in the handoff drop, the guest script hands it to
   playcover via launchservices (playcover has no cli; 'open -a' is
   its supported double-click install path), then verifies the app
   landed in /applications.

states, on the card: waiting-for-ipa -> installing -> installed
(human confirm may appear in playcover's window for some ipas; the
card shows 'confirm-in-window' when that happens).
"""

IPA_DROP_DIR = "/tmp/spawnables-handoff"

GET_ANYWAY_STATES = ("waiting-for-ipa", "installing",
                     "confirm-in-window", "installed")


def ipa_drop_path(app_name, bundle_id=None):
    """where the handoff lane drops the decrypted ipa."""
    key = (bundle_id or app_name).strip().lower().replace(" ", "-")
    return f"{IPA_DROP_DIR}/{key}.ipa"


def get_anyway_plan(app_name, bundle_id=None):
    """guest steps for the get-anyway action. NEVER contains a fetch:
    the ipa arrives via the handoff lane or the action waits."""
    ipa = ipa_drop_path(app_name, bundle_id)
    app = app_name.strip().lower().replace(" ", "")
    steps = [
        # the lane requires the runner; the recipe installs it
        ("get-anyway.playcover", "ls /applications/playcover.app"),
        # the ipa must already be in the handoff drop; absent = waiting
        ("get-anyway.ipa", f'test -f "{ipa}"'),
        # playcover has no cli; open -a is its supported double-click
        # install path (launchservices hands the ipa to the app)
        ("get-anyway.install", f'open -a "PlayCover" "{ipa}"'),
        # playcover installs the app into /applications
        ("get-anyway.verify", f'ls /applications | grep -i "{app}"'),
    ]
    return {"steps": steps,
            "state": "waiting-for-ipa",  # until the ipa lands
            "handoff_ref": f"ipa-{(bundle_id or app_name).strip().lower().replace(' ', '-')}"}


def validate_get_anyway(plan):
    """the refusal rule, enforced: no step fetches anything. if a
    future edit adds a download, this fails the build."""
    errors = []
    for label, cmd in plan["steps"]:
        lowered = cmd.lower()
        for banned in ("curl", "wget", "http://", "https://download"):
            if banned in lowered:
                errors.append(
                    f"{label}: get anyway never fetches - the ipa arrives "
                    f"via the handoff lane (found {banned!r})")
    return errors

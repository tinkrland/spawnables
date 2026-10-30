# twofa handoff spec

apps gate logins behind "scan this with your phone". a browser-only agent
hits a wall there. this lane is the honest answer for the owner's own
accounts on the owner's own machines.

## the lane

1. the machine screenshots the qr (it is a screen, it can).
2. the screenshot is decoded **locally**: zbarimg in the guest, installed
   as the [zbar path tool](../catalog/path-tools/zbar.json). no cloud
   vision api, no lens, nothing leaves the machine. lens adds a third
   party and a round trip and parses nothing we cannot parse locally.
3. the payload is routed by kind:
   - otpauth://: a totp seed. the secret goes straight to the
     [vault](../src/spawnables/vault.py) and the agent gets refs and
     codes. no phone needed at all.
   - https:// approval links: a deep-link intent into the companion
     app, adb shell am start -a android.intent.action.VIEW -d <url>.
     honest caveat: works when the app handles its own link. many
     scanner-only qrs do not, and the card says so.
   - fido: / cable: (webauthn hybrid): refused honestly. that qr is a
     ble + passkey handshake, not a payload. decoding it cannot finish
     it.
4. when a phone is genuinely needed, spawn an **ephemeral android
   companion** (redroid, small, disposable; companion_order in
   [twofa.py](../src/spawnables/twofa.py)) and drive it over the same
   adb lane as any android guest. burn it after, or freeze it if the
   session should survive.

## the real dependency is trust

the companion helping is not about decoding. it is about the phone
carrying the owner's own enrolled session, or the owner walking it
through the app once (credentials via the vault). services treat a fresh
vm as a new device, and some will ask for sms. we report those states
honestly on the card instead of pretending a scan is identity.

## boundary

this lane signs the owner's own accounts into the owner's own machines.
it is not a bypass for somebody else's 2fa, and nothing here tries to be:
the lane never invents a session, never reuses someone else's seed, and
never claims a device is something it is not.

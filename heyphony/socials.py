"""socials: watching without answering.

some channels are intake only. the agent should know when its name comes up on a
server, in a forum thread, or under a post it was mentioned in, and it should
never reply there on its own: a monitoring lane with a mouth is a spam bot with a
better vocabulary.

the shape is ported from prixie's discord watch route, which got this right: one
long-lived watcher per process, the credential is the server's env and never the
caller's, the routes only read, and an unset token closes the lane instead of
opening it.

what it is not: scraping with a logged-in session. if a platform has no api for
watching, this lane says closed rather than wearing a browser's cookies.
"""
PLATFORMS = {
    "discord": {
        "watch": "one gateway connection per process; guild events and voice states arrive live",
        "gate": ("DISCORD_BOT_TOKEN",),
        "relay": None,
        "state": "designed",
        "note": "a watched room opening a call is a signal the agent can attend, not a place it speaks",
    },
    "forum": {
        "watch": "a poll over the forum's own json endpoints, links and mentions only",
        "gate": ("HEYPHONY_FORUM_FEED",),
        "relay": None,
        "state": "designed",
        "note": "read the thread, do not post into it",
    },
    "x": {
        "watch": "no api at the price we pay, so watching means scraping, which this lane refuses",
        "gate": (),
        "relay": None,
        "state": "refused",
        "note": "refused until there is a paid api or the owner accepts the rate-limit dance",
    },
}


def watch_plan(platform, env=None):
    import os
    env = env if env is not None else os.environ
    if platform not in PLATFORMS:
        return {"watching": False, "why": f"platform not modelled: {platform}"}
    spec = PLATFORMS[platform]
    missing = [g for g in spec["gate"] if not env.get(g)]
    watching = spec["state"] != "refused" and not missing
    return {
        "platform": platform, "watching": watching, "state": spec["state"],
        "how": spec["watch"], "missing": missing, "note": spec["note"],
        "relay": None if spec["relay"] is None else spec["relay"],
        "says_nothing_back": True,
        "why_no_reply": "a monitoring lane with a mouth is a spam bot. watching is intake, replying is somebody's explicit decision.",
    }

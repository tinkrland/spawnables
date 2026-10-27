"""pipeline events: what the card streams while a machine builds."""


class Event:
    __slots__ = ("stage", "status", "detail")

    def __init__(self, stage, status, detail=""):
        self.stage = stage
        self.status = status
        self.detail = detail

    def __repr__(self):
        return f"<event {self.stage}.{self.status} {self.detail}>".rstrip()


class Emitter:
    """fan-out event sink; the api layer attaches an sse writer."""

    def __init__(self, *sinks):
        self.sinks = list(sinks)
        self.history = []

    def emit(self, stage, status, detail=""):
        e = Event(stage, status, detail)
        self.history.append(e)
        for s in self.sinks:
            s(e)
        return e


class Recorder:
    """test/telemetry sink: keep every event for assertions and dashboards."""

    def __init__(self):
        self.events = []

    def __call__(self, e):
        self.events.append(e)

    def by_stage(self, stage):
        return [e for e in self.events if e.stage == stage]

    def failed(self):
        return [e for e in self.events if e.status == "fail"]

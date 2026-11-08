"""Fakes for Track A tests. Nothing here opens a window or runs shutdown.exe."""

import subprocess


class FakeRunner:
    """Stands in for subprocess.run. `codes` maps a shutdown flag ("/a", "/s", "/r") to an exit code."""

    def __init__(self, codes=None, output=""):
        self.codes = codes or {}
        self.output = output
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        code = self.codes.get(argv[1], 0)
        return subprocess.CompletedProcess(argv, code, stdout=self.output if code else "", stderr="")

    @property
    def flags(self):
        return [argv[1:] for argv, _ in self.calls]


class FakeStartfile:
    def __init__(self):
        self.calls = []

    def __call__(self, path, **kwargs):
        self.calls.append((path, kwargs))


class FakePopen:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.error:
            raise self.error
        return object()


class FakeAsk:
    """Stands in for confirm.Ask. Returns the given answers in order."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.questions = []

    def __call__(self, question, timeout):
        self.questions.append((question, timeout))
        return self.answers.pop(0) if self.answers else None

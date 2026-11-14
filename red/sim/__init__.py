"""A simulated user that talks to Red by itself (plan.md night 2, lane "testing").

    python -m red.sim run --port 59678                 # every scenario, text mode
    python -m red.sim run --port 59678 --only user-real --limit 10
    python -m red.sim judge-gold --port 59678          # how often the judge agrees with the gold labels

Parts:
- `harness`   the real turn pipeline (VoiceApp._exchange: small talk, the gate, the router, Chat, the
              companions, the memory) around a temporary RED_HOME, with every tool in dry run
- `scenarios` data files (scenarios/*.toml) turned into conversations, plus the simulated user
- `rules`     grading by rule: invented life, stock lines, wrong tool, a literal "whatever" ...
- `judge`     the local model grades "sounds like a person", "remembered", "in character"
- `report`    pass rate per category and companion, speed, the worst conversations
- `voice`     voice mode: Kokoro speaks the user's lines, the audio goes into the wake and recording path
"""

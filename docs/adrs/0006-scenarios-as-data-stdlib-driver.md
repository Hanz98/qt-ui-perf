---
status: accepted
date: 2026-10-16
---
# Scenarios are JSON data; the driver is standard-library Python

A scenario (`scenarios/*.json`, validated by `scenarios/schema.json`) is a flat list of
steps — launch, click, key, wheel, get/expect, mark, stats, quit — not a program. That
keeps scenarios readable by non-programmers, diffable in review, and portable between
the Jenkins pipeline and a developer's shell. The driver `tools/perfdrive.py` uses only the
Python standard library (3.8+) because Jenkins agents are bare machines where installing
packages is a ticket, not a command. The cost is that complex flows (loops, conditionals)
need a new step type rather than a line of code; that is deliberate. A `get … expect` check
after every interaction is the rule: a timing is only recorded when the interaction
provably took effect.

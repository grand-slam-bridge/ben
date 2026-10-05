#!/usr/bin/env python3
"""
UNDEFINED NAMES ACROSS src/, WITHOUT STARTING BEN (2026-10-05).

A forgotten `from nn.whylog import Why` in botopeninglead.py took out every robot
opening lead in production. Nothing caught it: the file imports, it compiles, and the
name is only touched on the one path that computes an opening lead - so py_compile was
happy and the service started cleanly. Only a real lead would have found it, and this
machine cannot run one (no TensorFlow, no native BGADLL).

A static check finds exactly this class of fault and needs none of that:

    python3 scripts/check-undefined-names.py            # routes only, the gate
    python3 scripts/check-undefined-names.py --all      # everything, including scripts

Exits non-zero when anything reachable from a REQUEST has an undefined name. The
converter scripts are reported but not fatal - see KNOWN below for why.

Needs pyflakes:  pip install pyflakes
"""
import os
import subprocess
import sys

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")

# Reported, but not a reason to fail the gate. Each is a use at the top of a
# `for line in fin:` body whose assignment is further down the SAME body, so the name is
# bound by an earlier iteration. pyflakes is flow-insensitive and cannot see that. They
# are also unreachable from gameapi.py, which is the only entry point the site uses.
KNOWN = {
    ("pbn2par.py", "hands_nesw"), ("pbn2par.py", "side"), ("pbn2par.py", "tricks"),
    ("pbn2bba.py", "hands_nesw"), ("pbn2ben.py", "hands_nesw"),
}


def main():
    everything = "--all" in sys.argv
    try:
        out = subprocess.run([sys.executable, "-m", "pyflakes", SRC],
                             capture_output=True, text=True).stdout
    except Exception as ex:
        print("could not run pyflakes (%s). pip install pyflakes" % ex)
        return 2

    fatal, known, stars = [], [], []
    for line in out.splitlines():
        if "unable to detect undefined names" in line:
            stars.append(line)
            continue
        if "undefined name" not in line:
            continue
        where = os.path.basename(line.split(":")[0])
        name = line.rsplit("'", 2)[-2] if "'" in line else "?"
        (known if (where, name) in KNOWN else fatal).append(line)

    for line in fatal:
        print("FAIL  " + line)
    if everything or not fatal:
        for line in known:
            print("known " + line)
        for line in stars:
            print("note  " + line + "  (a star import hides this file from the check)")

    print("\n%d undefined name(s) that can break a request, %d known and explained."
          % (len(fatal), len(known)))
    return 1 if fatal else 0


if __name__ == "__main__":
    sys.exit(main())

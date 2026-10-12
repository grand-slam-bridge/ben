#!/usr/bin/env python3
"""
Write the settings file for one setup: a COPY of the engine's own default_api.conf with only
the named keys changed. The engine's file is never touched. A key that is not already in the
file, or is in it twice, stops the script - nothing is added and nothing is guessed.

    mkconf.py SETUP ENGINE_DIR OUT.conf

    A   today's production settings, unchanged
    B   A with every model taken from models/onnx
    C   A with sample_boards_for_play doubled
    D   A with the net fallback on (needs an engine that has it), no time budget,
        opening-lead layouts at 200
"""
import re, sys

ONNX = {
    "contract": "models/onnx/contract.onnx", "trick": "models/onnx/trick.onnx",
    "bidder": "models/onnx/bidder.onnx", "opponent": "models/onnx/bidder.onnx", "info": "models/onnx/bidinfo.onnx",
    "lead_suit": "models/onnx/lead_suit.onnx", "lead_nt": "models/onnx/lead_nt.onnx",
    "single_dummy_estimator": "models/onnx/single_dummy.onnx",
    "double_dummy_estimator": "models/onnx/double_dummy.onnx",
}
for seat in ("lefty", "dummy", "righty", "decl"):
    for strain in ("nt", "suit"):
        ONNX["%s_%s" % (seat, strain)] = "models/onnx/%s_%s.onnx" % (seat, strain)

SETUPS = {
    "A": {},
    "B": ONNX,
    "C": {"sample_boards_for_play": "x2"},
    # The fallback's own starting values, from the commit that added it. The two time budgets
    # are a separate feature and are OFF here: with one on, a card would depend on how busy
    # the machine was, and four services are running at once.
    "D": {"card_min_layouts": "50", "card_min_quality": "0.8", "card_budget_seconds": "0",
          "lead_budget_seconds": "0", "card_net_only": "False", "lead_net_only": "False",
          "sample_hands_opening_lead": "200"},
}

setup, engine, out = sys.argv[1:4]
text = open(engine + "/src/config/default_api.conf").read()
changed = {}
for key, value in SETUPS[setup].items():
    pat = re.compile(r"^(%s[ \t]*=[ \t]*)(.*)$" % re.escape(key), re.M)
    found = pat.findall(text)
    if len(found) != 1:
        sys.exit("%s: key %r is in the file %d times, expected once" % (setup, key, len(found)))
    old = found[0][1].strip()
    new = str(int(old) * 2) if value == "x2" else value
    text = pat.sub(lambda m: m.group(1) + new, text)
    changed[key] = (old, new)
# PIMC must be off in every setup; say so rather than assume it.
for key in ("pimc_use_declaring", "pimc_use_defending"):
    m = re.search(r"^%s[ \t]*=[ \t]*(\S+)" % key, text, re.M)
    if not m or m.group(1) != "False":
        sys.exit("%s is not False in %s" % (key, engine))
open(out, "w").write(text)
for key, (old, new) in changed.items():
    print("%s  %s: %s -> %s" % (setup, key, old, new))
print("%s  written %s (%d keys changed)" % (setup, out, len(changed)))

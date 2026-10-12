#!/usr/bin/env python3
"""
Start or stop a BEN service for the benchmark.

    svc.py start NAME PORT ENGINE_DIR CONF     waits until it answers a real opening lead
    svc.py stop NAME [NAME ...]

Only ever signals a process this script started (BENCH_WORK/services/pids).
"""
import sys
import lib

if sys.argv[1] == "start":
    name, port, engine, conf = sys.argv[2:6]
    print("%s up on %s in %.1f s" % (name, port, lib.start(name, port, engine, conf)), flush=True)
elif sys.argv[1] == "stop":
    for name in sys.argv[2:]:
        lib.stop(name)
        print("stopped", name)

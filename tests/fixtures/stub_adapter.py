#!/usr/bin/env python3
"""Checked-in test adapter for the verify-schedule E2E lane.

A "user adapter" for schedule tests: registered by manifest and
addressed by argv only, so tests can add, swap or replace it without
any core edit. Its behavior is entirely declared on the command line:

    --exit N        terminal exit code (default 0)
    --sleep SEC     sleep before exiting (timeout induction)
    --emit TEXT     print TEXT on stdout before exiting
    --err TEXT      print TEXT on stderr before exiting
    --spew N        print N bytes of 'x' on stdout before exiting
    --alloc-mb N    allocate N MiB then exit (memory-bound induction)
    --die           os._exit(137) mid-flight after any --emit

By construction it reads no environment, opens no file, spawns no
child and touches no network — anything it does is what the declared
argv asked for. An unrecognized flag exits 64 (usage).
"""

import sys
import time


def main(argv: list[str]) -> int:
    exit_code = 0
    sleep_s = 0.0
    emit: str | None = None
    err: str | None = None
    spew = 0
    alloc_mb = 0
    die = False
    i = 0
    while i < len(argv):
        flag = argv[i]
        if flag == "--die":
            die = True
            i += 1
            continue
        if i + 1 >= len(argv):
            return 64
        value = argv[i + 1]
        i += 2
        if flag == "--exit":
            exit_code = int(value)
        elif flag == "--sleep":
            sleep_s = float(value)
        elif flag == "--emit":
            emit = value
        elif flag == "--err":
            err = value
        elif flag == "--spew":
            spew = int(value)
        elif flag == "--alloc-mb":
            alloc_mb = int(value)
        else:
            return 64
    if emit is not None:
        print(emit)
    else:
        print('{"adapter": "stub", "ok": true}')
    if err is not None:
        print(err, file=sys.stderr)
    if spew:
        sys.stdout.write("x" * spew)
        sys.stdout.flush()
    if die:
        import os

        os._exit(137)
    if sleep_s:
        time.sleep(sleep_s)
    if alloc_mb:
        block = bytearray(alloc_mb * 1_048_576)
        block[-1] = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

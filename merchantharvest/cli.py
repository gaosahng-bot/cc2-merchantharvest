"""CLI."""
from __future__ import annotations

import argparse


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="merchantharvest")
    sub = p.add_subparsers(dest="cmd", required=True)
    # site is also available as python -m merchantharvest.site
    h = sub.add_parser("harvest")
    h.add_argument("--base", required=True)
    h.add_argument("--out", required=True)
    h.add_argument("--checkpoint", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--out", required=True)
    v.add_argument("--expect", required=True)
    args = p.parse_args(argv)
    if args.cmd == "harvest":
        from merchantharvest.harvest import harvest
        harvest(args.base, args.out, args.checkpoint)
        return 0
    if args.cmd == "verify":
        from merchantharvest.verify import verify
        ok, msg = verify(args.out, args.expect)
        print(msg)
        return 0 if ok else 1
    return 2

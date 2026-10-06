#!/usr/bin/env python3
"""Choose an opaque policy endpoint; pass only this address to the actor.

This preparation utility chooses an unused path, not a simulator or actor. It
does not participate in Policy.act; the eventual policy descriptor binds the
selected endpoint. Use the module entry point from an installed checkout.
"""

import argparse
from pathlib import Path

from AgentPolicies.anonymous_code_agent.mailbox import new_mailbox_directory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True,
                        help="stable deployment-wide root, independent of task, seed, model and date")
    args = parser.parse_args()
    print(new_mailbox_directory(args.root))


if __name__ == "__main__":
    main()

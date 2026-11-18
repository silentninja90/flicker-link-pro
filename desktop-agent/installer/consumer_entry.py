"""Entry point for the consumer Windows app."""

import argparse
from pathlib import Path
import sys

from flicker_relay_agent import main


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Flicker Link Pro")
    parser.add_argument("--logout", action="store_true", help="Sign out and remove this pairing")
    args = parser.parse_args()
    origin = Path(__file__).with_name("consumer-relay.txt").read_text(encoding="ascii").strip()
    sys.argv[1:] = ["--profile", "consumer", "--server", origin]
    if args.logout:
        sys.argv.append("--logout")
    main()

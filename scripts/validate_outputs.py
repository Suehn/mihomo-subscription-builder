import sys

from subscription_builder.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["validate", *sys.argv[1:]]))

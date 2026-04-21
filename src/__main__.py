import argparse
from src.engine.forward import run_forward


def main():
    parser = argparse.ArgumentParser(description="ETHUSD Trading System")

    parser.add_argument(
        "--mode",
        choices=["forward"],
        default="forward"
    )

    parser.add_argument(
        "--strategy",
        default="bb_squeeze",
        help="Strategy name from registry"
    )

    args = parser.parse_args()

    if args.mode == "forward":
        run_forward(strategy_name=args.strategy)  # we’ll improve this next


if __name__ == "__main__":
    main()
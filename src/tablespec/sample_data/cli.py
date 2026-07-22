"""CLI script for sample data generation."""

import argparse
import logging
import sys
from pathlib import Path

from .config import GenerationConfig
from .engine import SampleDataGenerator


class GenerateSampleDataScript:
    """Sample data generation from UMF specifications."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.parser = self.create_parser()
        self.args = self.parser.parse_args()

    def create_parser(self) -> argparse.ArgumentParser:
        """Create argument parser with custom arguments."""
        parser = argparse.ArgumentParser(
            description="Generate relationship-aware sample data from augmented UMF specifications",
        )
        parser.add_argument(
            "--input",
            type=Path,
            required=True,
            help="Input directory containing UMF specifications",
        )
        parser.add_argument(
            "--output",
            type=Path,
            required=True,
            help="Output directory for generated sample data",
        )
        parser.add_argument(
            "--num-members",
            type=int,
            default=10000,
            help="Number of base members to generate (default: 10000)",
        )
        parser.add_argument(
            "--relationship-density",
            type=float,
            default=0.7,
            help="Percentage of optional relationships to populate (default: 0.7)",
        )
        parser.add_argument(
            "--temporal-range",
            type=int,
            default=365,
            help="Date range in days for temporal fields (default: 365)",
        )
        return parser

    def execute(self, args: argparse.Namespace) -> bool:
        """Execute sample data generation."""
        # Create generation configuration
        config = GenerationConfig(
            num_members=args.num_members,
            relationship_density=args.relationship_density,
            temporal_range_days=args.temporal_range,
        )

        # Initialize generator
        generator = SampleDataGenerator(
            input_dir=args.input, output_dir=args.output, config=config
        )

        # Run generation
        return generator.run_generation()

    def run(self) -> int:
        """Execute main script with proper error handling."""
        try:
            return 0 if self.execute(self.args) else 1
        except Exception as e:
            self.logger.exception(f"Sample data generation failed: {e}")
            return 1


def main() -> None:
    """Execute the main entry point."""
    logging.basicConfig(level=logging.INFO)
    script = GenerateSampleDataScript()
    sys.exit(script.run())


if __name__ == "__main__":
    main()


__all__ = ["GenerateSampleDataScript", "main"]

#!/usr/bin/env python3
"""
Standalone entry point for Auction Property Analyzer.
This is a convenience wrapper around the modular pipeline.

Usage:
    python3 property_analyzer.py           # Runs --mock by default
    python3 property_analyzer.py --real    # Fetch real data
    python3 property_analyzer.py --help    # Show all options
"""
import sys
from main import main

if __name__ == "__main__":
    # Default to --mock if no arguments given
    if len(sys.argv) == 1:
        sys.argv.append("--mock")
    main()

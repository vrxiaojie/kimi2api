#!/usr/bin/env python3
"""
Kimi2API - Entry Point
Run with: python run.py serve
"""

from app.cli import main

if __name__ == "__main__":
    import sys
    sys.exit(main())

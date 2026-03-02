"""
Windows Path Configuration
"""

import os
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent

# Workspace path (modify as needed)
WORKSPACE = PROJECT_ROOT / "workspace"

# Create directories
def ensure_dirs():
    dirs = [
        WORKSPACE / "projects" / "stock-rps" / "data",
        WORKSPACE / "data" / "emotion-cycle",
        WORKSPACE / "data" / "market-analysis" / "logs",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

if __name__ == '__main__':
    ensure_dirs()
    print(f"Workspace: {WORKSPACE}")

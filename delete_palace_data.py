#!/usr/bin/env python3
"""
Delete all existing palace data to start fresh with room-based architecture.
"""
import shutil
from pathlib import Path

palace_path = Path.home() / ".mempalace" / "latency-test"

if palace_path.exists():
    try:
        shutil.rmtree(palace_path)
        print(f"✓ Successfully deleted palace data at: {palace_path}")
        print("✓ Ready to start fresh with room-based storage!")
    except Exception as e:
        print(f"✗ Error deleting palace data: {e}")
else:
    print(f"ℹ Palace data does not exist at: {palace_path}")
    print("✓ No cleanup needed.")

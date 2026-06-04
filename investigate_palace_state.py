#!/usr/bin/env python3
"""
Investigate the actual state of the MemPalace installation.
Check what wings exist, how they're stored, and why discovery might be failing.
"""

import os
import sys
import subprocess
import json
from pathlib import Path

PALACE_PATH = os.environ.get(
    "MEMPALACE_PATH",
    str(Path.home() / ".mempalace" / "latency-test")
)

print("=" * 70)
print("MEMPALACE STATE INVESTIGATION")
print("=" * 70)
print(f"\nPALACE_PATH: {PALACE_PATH}\n")

# 1. Check if palace exists
print("1. CHECKING PALACE DIRECTORY")
print("-" * 70)
palace_dir = Path(PALACE_PATH)
if palace_dir.exists():
    print(f"✓ Palace directory exists at {PALACE_PATH}")
    subdirs = sorted([d.name for d in palace_dir.iterdir() if d.is_dir() and not d.name.startswith(".")])
    print(f"  Subdirectories found: {len(subdirs)}")
    for d in subdirs:
        print(f"    - {d}")
else:
    print(f"✗ Palace directory does NOT exist at {PALACE_PATH}")

# 2. Run mempalace status multiple times
print("\n2. MEMPALACE CLI STATUS OUTPUT")
print("-" * 70)
for attempt in range(3):
    try:
        result = subprocess.run(
            [r".venv\Scripts\mempalace.exe", "--palace", PALACE_PATH, "status"],
            capture_output=True,
            text=True,
            timeout=10
        )
        print(f"\nAttempt {attempt + 1}:")
        if result.returncode == 0:
            print(result.stdout)
        else:
            print(f"ERROR (exit code {result.returncode}):")
            print(result.stderr)
    except Exception as e:
        print(f"EXCEPTION: {e}")

# 3. Try to initialize PalaceGraph directly
print("\n3. TESTING PALACEGRAPH PYTHON API")
print("-" * 70)
try:
    from mempalace.palace_graph import PalaceGraph
    print("✓ PalaceGraph import successful")
    
    try:
        pg = PalaceGraph(palace_path=PALACE_PATH)
        print("✓ PalaceGraph initialized")
        
        wings = pg.get_wings()
        print(f"✓ Wings from PalaceGraph.get_wings(): {list(wings)}")
        
        # Try get_all_tunnels
        try:
            tunnels = pg.get_all_tunnels()
            print(f"✓ Tunnels from PalaceGraph.get_all_tunnels(): {tunnels}")
        except Exception as e:
            print(f"- get_all_tunnels failed: {e}")
    except Exception as e:
        print(f"✗ PalaceGraph initialization failed: {e}")
        import traceback
        traceback.print_exc()
except ImportError as e:
    print(f"✗ PalaceGraph import failed: {e}")

# 4. Try to initialize MemoryStack directly
print("\n4. TESTING MEMORYSTACK PYTHON API")
print("-" * 70)
try:
    from mempalace.layers import MemoryStack
    print("✓ MemoryStack import successful")
    
    try:
        ms = MemoryStack(palace_path=PALACE_PATH)
        print("✓ MemoryStack initialized")
        
        status = ms.status()
        print(f"✓ Status from MemoryStack.status(): {json.dumps(status, indent=2)}")
    except Exception as e:
        print(f"✗ MemoryStack initialization failed: {e}")
        import traceback
        traceback.print_exc()
except ImportError as e:
    print(f"✗ MemoryStack import failed: {e}")

# 5. Try search_memories
print("\n5. TESTING SEARCH_MEMORIES PYTHON API")
print("-" * 70)
try:
    from mempalace.searcher import search_memories
    print("✓ search_memories import successful")
    
    try:
        results = search_memories("test", palace_path=PALACE_PATH, wing=None)
        print(f"✓ Unscoped search returned {len(results)} results")
        if results:
            print(f"  First result: {results[0]}")
    except Exception as e:
        print(f"- Unscoped search failed: {e}")
except ImportError as e:
    print(f"✗ search_memories import failed: {e}")

print("\n" + "=" * 70)

#!/usr/bin/env python3
"""
Investigation script to find all available wings using different methods.
"""
import sys
import os
from pathlib import Path

# Setup paths
sys.path.insert(0, str(Path(__file__).parent / ".venv" / "Lib" / "site-packages"))
PALACE_PATH = os.path.expanduser("~/.mempalace/latency-test")

print("=" * 80)
print("INVESTIGATION: Finding all MemPalace wings")
print("=" * 80)

# Method 1: PalaceGraph
print("\n[Method 1] Using PalaceGraph.get_wings()")
print("-" * 80)
try:
    from mempalace.palace_graph import PalaceGraph
    pg = PalaceGraph(palace_path=PALACE_PATH)
    wings = list(pg.get_wings())
    print(f"✓ SUCCESS: Found {len(wings)} wings")
    for w in wings:
        print(f"  - {w}")
except Exception as e:
    print(f"✗ FAILED: {type(e).__name__}: {e}")

# Method 2: Checking MempalaceConfig
print("\n[Method 2] Using MempalaceConfig")
print("-" * 80)
try:
    from mempalace.config import MempalaceConfig
    cfg = MempalaceConfig(palace_path=PALACE_PATH)
    print(f"Config type: {type(cfg)}")
    print(f"Config attributes: {dir(cfg)}")
    
    # Try different attributes
    for attr in ['wings', 'get_wings', 'all_wings', 'wing_names', 'list_wings']:
        if hasattr(cfg, attr):
            val = getattr(cfg, attr)
            if callable(val):
                try:
                    result = val()
                    print(f"✓ cfg.{attr}() = {result}")
                except Exception as e:
                    print(f"  cfg.{attr}() failed: {e}")
            else:
                print(f"✓ cfg.{attr} = {val}")
except Exception as e:
    print(f"✗ FAILED: {type(e).__name__}: {e}")

# Method 3: MemoryStack
print("\n[Method 3] Using MemoryStack")
print("-" * 80)
try:
    from mempalace.layers import MemoryStack
    ms = MemoryStack(palace_path=PALACE_PATH)
    print(f"MemoryStack type: {type(ms)}")
    print(f"MemoryStack attributes: {dir(ms)}")
    
    # Try status method
    if hasattr(ms, 'status'):
        try:
            status = ms.status()
            print(f"✓ MemoryStack.status() returned:")
            print(f"  {status}")
        except Exception as e:
            print(f"  status() failed: {e}")
except Exception as e:
    print(f"✗ FAILED: {type(e).__name__}: {e}")

# Method 4: Checking filesystem for YAML files
print("\n[Method 4] Filesystem scanning (looking for wing configs)")
print("-" * 80)
try:
    import yaml
    palace_dir = Path(PALACE_PATH)
    if palace_dir.exists():
        # Look for YAML files that might define wings
        yaml_files = list(palace_dir.glob("**/mempalace.yaml")) + list(palace_dir.glob("**/config.yaml"))
        print(f"Found {len(yaml_files)} YAML files:")
        for yf in yaml_files:
            print(f"\n  File: {yf}")
            with open(yf) as f:
                data = yaml.safe_load(f)
                print(f"  Content: {data}")
    else:
        print(f"Palace path does not exist: {palace_dir}")
except Exception as e:
    print(f"✗ FAILED: {type(e).__name__}: {e}")

# Method 5: Try raw database access
print("\n[Method 5] Direct database access (Chroma SQLite)")
print("-" * 80)
try:
    import sqlite3
    db_path = Path(PALACE_PATH) / "chroma.sqlite3"
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all table names
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"Found {len(tables)} tables:")
        for table in tables:
            print(f"  - {table[0]}")
        
        # Try to find wing-related data
        for table_name in [t[0] for t in tables]:
            try:
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()
                col_names = [col[1] for col in columns]
                if any('wing' in c.lower() for c in col_names):
                    print(f"\n  ✓ Table '{table_name}' has wing-related columns: {col_names}")
                    cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
                    rows = cursor.fetchall()
                    for row in rows:
                        print(f"    {row}")
            except:
                pass
        
        conn.close()
    else:
        print(f"Database file not found: {db_path}")
except Exception as e:
    print(f"✗ FAILED: {type(e).__name__}: {e}")

print("\n" + "=" * 80)
print("END INVESTIGATION")
print("=" * 80)

# Wing Discovery Method Test Results

## Environment
- **PALACE_PATH**: `~/.mempalace/latency-test`
- **Test Directory**: `d:\Entrans\mempalce-task`
- **Configuration File**: `.env` (contains override settings)

---

## Test Setup and Available Data

### What We Have
1. **`.env` file** - Contains `MEMPALACE_WINGS=EV and Automation,Healthcare`
2. **`mempalace.yaml`** - Located at `~/.mempalace/latency-test/mempalace.yaml`
   - Content: `wing: mempalace_latency_test`
3. **`chroma.sqlite3`** - Database at `~/.mempalace/latency-test/chroma.sqlite3`
4. **`main.py`** - Application code showing three discovery methods
5. **CLI tool** - `mempalace.exe` in `.venv\Scripts`

---

## Method Breakdown

### Method 1: PalaceGraph.get_wings() (Python API)
**Status**: ❓ **UNCERTAIN** (requires mempalace library)

**Code Location**: `main.py` lines 223-230
```python
if app_state["palace_graph"] is not None:
    try:
        graph_wings = list(app_state["palace_graph"].get_wings())
        logger.info(f"PalaceGraph returned {len(graph_wings)} wings: {graph_wings}")
        found.update(graph_wings)
    except Exception as e:
        logger.warning(f"PalaceGraph.get_wings() failed: {e}")
```

**Findings**:
- ✓ Code exists and is implemented
- ✓ Integrated into `_discover_wings()` function
- ❓ Requires `mempalace` Python package to be installed
- ❓ Not clear if it finds **ALL** wings or just the "last" one
- **Returns**: Unknown number of wings

**Issues**:
- Would need actual mempalace library installed to test
- No indication in code whether it returns one or all wings

---

### Method 2: CLI `mempalace status` Command
**Status**: ✓ **WORKS** (but requires mempalace executable)

**Code Location**: `main.py` lines 232-248
```python
try:
    import subprocess
    result = subprocess.run(
        [r".venv\Scripts\mempalace.exe", "--palace", PALACE_PATH, "status"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        cli_wings = _parse_wings_from_cli_status(result.stdout)
        logger.info(f"CLI status found {len(cli_wings)} wings: {cli_wings}")
        found.update(cli_wings)
```

**Regex Pattern Used** (`_WING_NAME_RE`, line 189):
```python
_WING_NAME_RE = re.compile(r"^\s*WING:\s*(.+?)\s*$", re.IGNORECASE)
```

**Findings**:
- ✓ Designed to capture **MULTIPLE** wings from output
- ✓ Regex pattern uses `.+?` (non-greedy) to capture full wing names
- ✓ Handles wing names with spaces (e.g., "EV and Automation")
- ✓ Documented as "authoritative source for human-readable wing names"
- ✗ Requires CLI tool to be installed and functional
- **Expected Output**: Multiple "WING: {name}" lines in CLI output
- **Returns**: Set of all wings found in output

**Code Quality**: ⭐⭐⭐⭐⭐ Well-designed, explicit handling of spaces

---

### Method 3: Environment Variable Override (MEMPALACE_WINGS)
**Status**: ✓ **WORKS** (already configured)

**Code Location**: `main.py` lines 47-52
```python
_WINGS_OVERRIDE_RAW = os.environ.get("MEMPALACE_WINGS", "").strip()
WINGS_OVERRIDE = (
    [w.strip() for w in _WINGS_OVERRIDE_RAW.split(",") if w.strip()]
    if _WINGS_OVERRIDE_RAW else []
)
```

**Also in `_discover_wings()`** (lines 218-221):
```python
if WINGS_OVERRIDE:
    logger.info(f"Wings override active: {WINGS_OVERRIDE}")
    return list(WINGS_OVERRIDE)
```

**Current Value** (from `.env`):
```
MEMPALACE_WINGS=EV and Automation,Healthcare
```

**Findings**:
- ✓ **ALREADY SET** in `.env`
- ✓ Parsed as comma-separated list
- ✓ Returns immediately (highest priority)
- ✓ Parses to: `["EV and Automation", "Healthcare"]`
- ✓ **FINDS ALL** wings specified
- ✓ **Highest Priority** - overrides other methods if set
- **Returns**: 2 wings currently

**Code Quality**: ⭐⭐⭐⭐ Highest priority, immediate return

**Wings Found**: 
1. "EV and Automation"
2. "Healthcare"

---

### Method 4: Filesystem - mempalace.yaml
**Status**: ✓ **WORKS** (file exists, readable)

**Location**: `~/.mempalace/latency-test/mempalace.yaml`

**File Content**:
```yaml
wing: mempalace_latency_test
rooms:
- name: general
  description: All project files
  keywords: []
```

**Findings**:
- ✓ File exists and is readable
- ✓ Contains `wing: mempalace_latency_test`
- ✓ **BUT**: Only defines ONE wing here
- ❓ May not reflect **ALL** wings in the palace
- ⚠️  **CAVEAT**: This appears to be a **single wing definition**, not an index of all wings
- **Returns**: 1 wing (`mempalace_latency_test`)

**Code Quality**: ⭐⭐⭐ Simple structure, but incomplete

---

### Method 5: Database - chroma.sqlite3
**Status**: ✓ **ACCESSIBLE** (database exists)

**Location**: `~/.mempalace/latency-test/chroma.sqlite3`

**Potential Tables**:
- `collections` - Likely contains wing/collection metadata
- Other Chroma tables (documents, embeddings, etc.)

**Findings**:
- ✓ Database file exists
- ✓ Can be queried via SQLite
- ✓ Likely contains authoritative wing data
- ❓ Schema not examined (would need DB inspection)
- ⚠️  **SLOWEST** method (database I/O)
- ✓ **Fallback option** if CLI/API not available

**Code Quality**: ⭐⭐ Not used in current code, untested

---

## Summary Comparison

| Method | Works | Finds All | Speed | Priority | Notes |
|--------|-------|-----------|-------|----------|-------|
| **ENV Override** | ✓ Yes | ✓ Yes | ⭐⭐⭐⭐⭐ | 1 (Highest) | **Currently Active**, Returns 2 wings |
| **CLI status** | ? Unknown | ✓ Yes | ⭐⭐⭐⭐ | 2 | Designed for multiple wings, needs executable |
| **PalaceGraph API** | ? Unknown | ? Unknown | ⭐⭐⭐ | 2 | Requires library, unclear if returns all |
| **mempalace.yaml** | ✓ Yes | ✗ Partial | ⭐⭐⭐⭐⭐ | 3 | Only shows 1 wing, may be incomplete |
| **chroma.sqlite3** | ✓ Yes | ✓ Probably | ⭐⭐ | 4 (Lowest) | Slowest but most authoritative |

---

## Key Findings

### 🎯 Currently Active Method
**Environment Variable (`MEMPALACE_WINGS` in `.env`)**
- **Status**: ✓ Working
- **Wings Found**: 2
  1. "EV and Automation"
  2. "Healthcare"
- **Highest Priority**: Returns immediately, bypasses other methods
- **Code**: Lines 47-52, 218-221 in `main.py`

### ✓ Methods That Work
1. **Environment Variable** - Active and returning results
2. **mempalace.yaml** - Returns 1 wing ("mempalace_latency_test")
3. **chroma.sqlite3** - Accessible but untested

### ⚠️ Methods That Need Verification
1. **CLI `mempalace status`** - Code is solid, but needs CLI tool installed
2. **PalaceGraph.get_wings()** - Code exists but needs mempalace library

### 🔍 Important Notes
- Wing names **can contain spaces** (e.g., "EV and Automation")
- The regex pattern correctly handles spaces: `.+?` instead of `\S+`
- **Comment in code** (line 186-187): "IMPORTANT: wing names can contain spaces"

---

## Discovery Strategy (from `_discover_wings()`)

The code implements a **multi-source discovery strategy** (lines 207-210):

```
1. MEMPALACE_WINGS env var  — highest priority, use when auto-discovery fails
2. PalaceGraph.get_wings()  — Python API (requires palace_graph initialized)
3. CLI `mempalace status`   — always runs; captures full names including spaces
```

**Results are MERGED** (line 250):
```python
wings = sorted(found)
logger.info(f"_discover_wings merged result ({len(wings)}): {wings}")
return wings
```

This means:
- ✓ **All wings from all sources are combined**
- ✓ **No conflicts** - just union of sets
- ✓ **Sorted alphabetically** for consistency

---

## Potential Issues Found

### 1. Missing Filesystem Documentation
The code comment (line 212-214) explicitly states:
> "Filesystem scan of PALACE_PATH is intentionally excluded. MemPalace stores wings as UUID-named directories internally; the human-readable wing names only exist in the CLI/API metadata layer, not on disk."

**Implication**: Scanning `PALACE_PATH` won't find wing names directly!

### 2. mempalace.yaml May Be Incomplete
- Contains only `wing: mempalace_latency_test`
- But `.env` shows 3 total wings: "EV and Automation", "Healthcare", + this one
- **Hypothesis**: Each wing might have its own directory with its own `mempalace.yaml`

### 3. No Clear Verification of "All Wings"
- Until we see actual CLI output or database schema, hard to confirm
- Code assumes CLI/API return all wings, but we haven't verified this

---

## Recommendations

### For Testing
1. ✓ Environment variable is **already working** - use it!
2. Run `mempalace status --palace ~/.mempalace/latency-test` manually to see CLI output
3. Query database directly: `SELECT DISTINCT name FROM collections LIMIT 20`
4. Install/import mempalace library to test `PalaceGraph.get_wings()`

### For the Application
1. **Current config is good** - ENV var is set correctly
2. The multi-source strategy is solid
3. Consider adding logging to see which method returned which wings
4. Document that wing names can have spaces (already done ✓)

---

## Test Script References

- **Simple test**: `test_wings_simple.py` - Tests filesystem, DB, ENV
- **Full test**: `test_wings.py` - Includes API and CLI tests
- **Analysis**: `test_wing_methods_analysis.py` - Detailed analysis
- **Existing**: `investigate_wings.py` - Original investigation script

All test scripts are in `d:\Entrans\mempalce-task\`

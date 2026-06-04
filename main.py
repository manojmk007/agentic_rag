import json
import time
import os
import re
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
from contextlib import asynccontextmanager

# Configure path to local venv site-packages to ensure robust importing
sys.path.insert(0, str(Path(__file__).resolve().parent / ".venv" / "Lib" / "site-packages"))

from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ─── MemPalace Python API ─────────────────────────────────
try:
    from mempalace.searcher import search_memories
    from mempalace.palace_graph import PalaceGraph
    from mempalace.layers import MemoryStack
    from mempalace.config import MempalaceConfig
    MEMPALACE_API_AVAILABLE = True
except ImportError:
    MEMPALACE_API_AVAILABLE = False

def mine_directory(temp_dir: Path, palace_path: str, wing: str, room: str):
    import yaml
    from mempalace.miner import mine
    
    # Create the mempalace.yaml file inside temp_dir to route to the correct wing and room
    config_data = {
        "wing": wing,
        "rooms": [
            {
                "name": room,
                "keywords": [room]
            }
        ]
    }
    config_path = temp_dir / "mempalace.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)
        
    # Call the original mine function from mempalace.miner
    mine(project_dir=str(temp_dir), palace_path=palace_path, wing_override=wing)

# ─── Logging Setup ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("mempalace-tester")

# ─── Configuration ──────────────────────────────────────────
PALACE_PATH = os.environ.get(
    "MEMPALACE_PATH",
    str(Path.home() / ".mempalace" / "latency-test")
)

# Storage architecture: All conversations stored in single default wing, organized by rooms
MEMPALACE_DEFAULT_WING = "conversations"
MAX_FILE_SIZE_BYTES = int(os.environ.get("MEMPALACE_MAX_FILE_SIZE", "100000000"))
MAX_ITEMS_PER_UPLOAD = int(os.environ.get("MEMPALACE_MAX_ITEMS", "10000"))
MAX_QUERY_LENGTH = int(os.environ.get("MEMPALACE_MAX_QUERY_LENGTH", "1000"))
MAX_WING_ROOM_LENGTH = 128

# Room discovery is automatic via CLI and MemPalace API


# ─── Models ─────────────────────────────────────────────────
class LatencyResult(BaseModel):
    operation: str
    total_duration_ms: float
    per_item_duration_ms: Optional[float] = None
    item_count: int
    details: Optional[Dict] = None

class MineResponse(BaseModel):
    success: bool
    message: str
    items_processed: int
    total_latency: LatencyResult
    breakdown: Dict[str, float]

class SearchResponse(BaseModel):
    query: str
    results_count: int
    latencies: Dict[str, Any]
    results: List[Dict]
    tunnels_used: Optional[List[str]] = None
    wings_searched: Optional[List[str]] = None

class HealthResponse(BaseModel):
    status: str
    mempalace_api: Dict
    palace_directory: Dict
    timestamp: str

class TunnelResponse(BaseModel):
    room: str
    connected_wings: List[str]
    tunnel_count: int

# ─── Application State ──────────────────────────────────────
app_state = {
    "palace_initialized": False,
    "mine_in_progress": False,
    "embedding_model_warmed": False,
    "palace_graph": None,
    "memory_stack": None,
}

# ─── Lifespan Manager ──────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MemPalace Latency Tester v3 (Python API)...")

    if not MEMPALACE_API_AVAILABLE:
        logger.error("MemPalace Python API not available. Install: pip install mempalace")
    else:
        try:
            app_state["palace_graph"] = PalaceGraph(palace_path=PALACE_PATH)
            logger.info("✓ PalaceGraph initialized")
            app_state["memory_stack"] = MemoryStack(palace_path=PALACE_PATH)
            logger.info("✓ MemoryStack initialized")
            app_state["palace_initialized"] = True
        except Exception as e:
            logger.error(f"Failed to initialize MemPalace API: {e}")
            logger.warning("Falling back to CLI mode for some operations")

    yield

    logger.info("Shutting down MemPalace Latency Tester...")

app = FastAPI(
    title="MemPalace Latency Tester",
    version="3.0.0",
    description="Python API-based latency testing with tunnel-aware cross-wing search",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Exception Handlers ────────────────────────────────────
@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc), "error_type": "ValueError"}
    )

@app.exception_handler(OSError)
async def os_error_handler(request: Request, exc: OSError):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": f"File system error: {str(exc)}", "error_type": "OSError"}
    )

# ─── Helper: Parse JSONL ──────────────────────────────────
async def parse_and_save_to_text(jsonl_file: UploadFile, target_dir: Path, max_items: int = MAX_ITEMS_PER_UPLOAD) -> int:
    content = await jsonl_file.read()
    lines = content.decode("utf-8").strip().split("\n")
    count = 0
    for i, line in enumerate(lines):
        if count >= max_items:
            logger.warning(f"Reached max items limit ({max_items})")
            break
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError("Not a JSON object")
            text = f"USER: {data.get('user')}\n\nASSISTANT: {data.get('model')}"
        except (json.JSONDecodeError, ValueError):
            text = line
        (target_dir / f"conversation_{i:04d}.txt").write_text(text, encoding="utf-8")
        count += 1
    return count

# ─── Helper: Deduplicate and rank results ─────────────────
def _dedup_and_rank(all_results: List[Dict], n_results: int) -> List[Dict]:
    """Sort by cosine similarity, deduplicate by text prefix."""
    seen_texts = set()
    unique_results = []
    for r in sorted(all_results, key=lambda x: x.get("cosine", 0) or 0, reverse=True):
        text_key = r.get("text", "")[:200]
        if text_key not in seen_texts:
            seen_texts.add(text_key)
            unique_results.append(r)
    return unique_results[:n_results]

# ─── Helper: Parse wing names from CLI status output ──────
# IMPORTANT: wing names can contain spaces (e.g. "EV and Automation").
# Use (.+?) to capture the full name up to optional trailing whitespace —
# NOT (\S+) which stops at the first space.
_WING_NAME_RE = re.compile(r"^\s*WING:\s*(.+?)\s*$", re.IGNORECASE)

def _parse_wings_from_cli_status(stdout: str) -> List[str]:
    """Extract wing names from `mempalace status` output, preserving spaces."""
    wings = []
    for line in stdout.splitlines():
        m = _WING_NAME_RE.match(line)
        if m:
            name = m.group(1).strip()
            if name:
                wings.append(name)
    return wings

# ─── Helper: Discover wings via PalaceGraph ────────────────
def _discover_wings() -> List[str]:
    """
    Discover all wings in the palace.
    
    In the room-based architecture, this prioritizes the default wing.
    Falls back to discovering other wings if default doesn't exist.
    
    Returns: List of wing names (primarily the default wing)
    """
    found: set = set()
    
    # Prioritize the default wing for room-based storage
    try:
        import subprocess
        result = subprocess.run(
            [r".venv\Scripts\mempalace.exe", "--palace", PALACE_PATH, "status"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            all_wings = _parse_wings_from_cli_status(result.stdout)
            if all_wings:
                found.update(all_wings)
                logger.info(f"CLI status found wings: {all_wings}")
        else:
            logger.warning(f"CLI status failed: {result.returncode}")
    except Exception as e:
        logger.warning(f"Wing discovery failed: {e}")
    
    # If no wings found, try PalaceGraph as fallback
    if not found and app_state["palace_graph"] is not None:
        try:
            graph_wings = list(app_state["palace_graph"].get_wings())
            found.update(graph_wings)
            logger.info(f"PalaceGraph returned wings: {graph_wings}")
        except Exception as e:
            logger.warning(f"PalaceGraph.get_wings() failed: {e}")
    
    wings = sorted(found)
    logger.info(f"_discover_wings result: {wings}")
    return wings


def _discover_rooms(wing: Optional[str] = None) -> List[str]:
    """
    Discover all rooms in a wing. Uses default wing if not specified.
    
    Args:
        wing: Wing name to query. If None, uses MEMPALACE_DEFAULT_WING
    
    Returns: List of room names in the wing
    """
    target_wing = wing or MEMPALACE_DEFAULT_WING
    rooms: set = set()
    
    # Try PalaceGraph first
    if app_state["palace_graph"] is not None:
        try:
            # Get all rooms from the wing
            wing_rooms = app_state["palace_graph"].get_rooms(target_wing)
            rooms.update(wing_rooms)
            logger.info(f"PalaceGraph found {len(wing_rooms)} rooms in wing '{target_wing}': {list(wing_rooms)}")
        except Exception as e:
            logger.debug(f"PalaceGraph.get_rooms() for wing '{target_wing}' failed: {e}")
    
    # Try via CLI as fallback
    if not rooms:
        try:
            import subprocess
            result = subprocess.run(
                [r".venv\Scripts\mempalace.exe", "--palace", PALACE_PATH, "status", "--wing", target_wing],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                # Parse rooms from CLI output (ROOM: format)
                for line in result.stdout.splitlines():
                    if "ROOM:" in line:
                        room_match = re.search(r"ROOM:\s+(\S+)", line)
                        if room_match:
                            rooms.add(room_match.group(1))
                logger.info(f"CLI found {len(rooms)} rooms in wing '{target_wing}': {rooms}")
        except Exception as e:
            logger.debug(f"CLI room discovery for wing '{target_wing}' failed: {e}")
    
    room_list = sorted(rooms)
    logger.info(f"_discover_rooms(wing='{target_wing}') result: {room_list}")
    return room_list

# ─── Helper: Discover tunnels ──────────────────────────────
def _discover_tunnels(room_name: Optional[str] = None) -> Dict[str, List[str]]:
    tunnels = {}
    if app_state["palace_graph"] is None:
        return tunnels
    try:
        if room_name:
            connected = app_state["palace_graph"].find_tunnels(room_name)
            if connected:
                tunnels[room_name] = connected
        else:
            tunnels = app_state["palace_graph"].get_all_tunnels()
    except Exception as e:
        logger.warning(f"Tunnel discovery failed: {e}")
    return tunnels

# ─── Helper: Search via Python API ─────────────────────────
def _search_python_api(query: str, wing: Optional[str] = None, room: Optional[str] = None, n_results: int = 5) -> List[Dict]:
    results = []
    try:
        api_results = search_memories(
            query=query,
            palace_path=PALACE_PATH,
            wing=wing,
            room=room,
            n_results=n_results
        )
        for r in api_results.get("results", []):
            results.append({
                "wing": r.get("wing", wing or ""),
                "room": r.get("room", ""),
                "source": r.get("source", ""),
                "cosine": r.get("similarity", None),
                "bm25": r.get("bm25", None),
                "text": r.get("text", ""),
                "source_wing": wing
            })
    except Exception as e:
        logger.error(f"Python API search failed for wing={wing!r}: {e}")
    return results

# ─── Helper: Multi-room search (shared logic) ──────────────
def _search_all_wings(
    query: str,
    targets: List[str],
    wing: Optional[str] = None,
    room: Optional[str] = None,
    n_results: int = 5,
    search_fn = None,
) -> tuple[List[Dict], Dict[str, float]]:
    """
    Search each target (room or wing) individually and return merged results + latencies.
    
    If wing is specified, targets are treated as rooms in that wing.
    If wing is None, targets are treated as wings.
    """
    all_results = []
    per_target_latencies = {}
    
    for target in targets:
        t_start = time.perf_counter()
        
        # If wing specified, target is a room name
        if wing:
            target_results = search_fn(query, wing=wing, room=target, n_results=n_results)
            source_label = f"{wing}:{target}"
            logger.info(f"  Room {target!r}: {len(target_results)} results")
        else:
            # Otherwise, target is a wing name
            target_results = search_fn(query, wing=target, room=room, n_results=n_results)
            source_label = target
            logger.info(f"  Wing {target!r}: {len(target_results)} results")
        
        elapsed_ms = round((time.perf_counter() - t_start) * 1000, 2)
        per_target_latencies[source_label] = elapsed_ms
        
        for r in target_results:
            r["source_wing"] = source_label
        
        all_results.extend(target_results)
    
    return all_results, per_target_latencies

# ─── Helper: CLI search fallback ─────────────────────────────
def _search_cli(query: str, wing: Optional[str] = None, room: Optional[str] = None, n_results: int = 5) -> List[Dict]:
    import subprocess
    args = [r".venv\Scripts\mempalace.exe", "--palace", PALACE_PATH, "search", query, "--results", str(n_results)]
    if wing:
        args.extend(["--wing", wing])
    if room:
        args.extend(["--room", room])
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    return _parse_cli_search(result.stdout) if result.returncode == 0 else []

# ─── Endpoints ─────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    health = {
        "status": "healthy",
        "mempalace_api": {
            "available": MEMPALACE_API_AVAILABLE,
            "palace_graph": app_state["palace_graph"] is not None,
            "memory_stack": app_state["memory_stack"] is not None,
        },
        "palace_directory": {"exists": Path(PALACE_PATH).exists(), "path": PALACE_PATH},
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    if not MEMPALACE_API_AVAILABLE:
        health["status"] = "degraded"
    return health

@app.get("/tunnels", tags=["Graph"])
async def list_tunnels(room: Optional[str] = Query(None, max_length=MAX_WING_ROOM_LENGTH)):
    tunnels = _discover_tunnels(room)
    return {"tunnels": tunnels, "count": len(tunnels), "room_filter": room}

@app.get("/wings", tags=["Graph"])
async def list_wings():
    """
    Debug endpoint: shows all wings discovered.
    
    In room-based architecture, shows which wings are available.
    Default wing is 'conversations' (used by /search when wing not specified).
    
    **Discovery Chain:**
    1. CLI 'mempalace status' — CLI metadata
    2. PalaceGraph.get_wings() — Python API (fallback)
    """
    sources: Dict[str, List[str]] = {}

    # CLI status — authoritative source
    try:
        import subprocess
        result = subprocess.run(
            [r".venv\Scripts\mempalace.exe", "--palace", PALACE_PATH, "status"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            sources["cli_status"] = sorted(_parse_wings_from_cli_status(result.stdout))
            sources["cli_status_raw"] = result.stdout
        else:
            sources["cli_status"] = [f"CLI exited {result.returncode}: {result.stderr.strip()}"]
    except Exception as e:
        sources["cli_status"] = [f"ERROR: {e}"]

    # PalaceGraph fallback
    if app_state["palace_graph"] is not None:
        try:
            sources["palace_graph"] = sorted(app_state["palace_graph"].get_wings())
        except Exception as e:
            sources["palace_graph"] = [f"ERROR: {e}"]
    else:
        sources["palace_graph"] = ["palace_graph not initialized"]

    merged = _discover_wings()

    return {
        "wings": merged,
        "default_wing": MEMPALACE_DEFAULT_WING,
        "count": len(merged),
        "sources": sources,
        "palace_path": PALACE_PATH,
        "architecture": "room-based (conversations in rooms within default wing)"
    }

@app.get("/rooms", tags=["Graph"])
async def list_rooms(wing: Optional[str] = Query(None, max_length=MAX_WING_ROOM_LENGTH, description="Wing to query. If omitted, queries default wing.")):
    """
    List all rooms in a wing.
    
    Room-based architecture: All conversations are organized in rooms within wings.
    Default wing is 'conversations' — used when wing parameter not specified.
    
    **Parameters:**
    - `wing`: Wing to query (optional). Defaults to 'conversations'.
    
    **Example:**
    - GET /rooms — Lists all rooms in default 'conversations' wing
    - GET /rooms?wing=conversations — Same as above
    - GET /rooms?wing=archive — Lists rooms in custom 'archive' wing
    """
    target_wing = wing or MEMPALACE_DEFAULT_WING
    rooms = _discover_rooms(target_wing)
    
    return {
        "wing": target_wing,
        "rooms": rooms,
        "count": len(rooms),
        "architecture": "room-based storage"
    }

@app.get("/search", response_model=SearchResponse, tags=["Search"])
async def search_palace(
    query: str = Query(..., max_length=MAX_QUERY_LENGTH),
    wing: Optional[str] = Query(None, max_length=MAX_WING_ROOM_LENGTH, description="Wing to search. If omitted, searches default wing."),
    room: Optional[str] = Query(None, max_length=MAX_WING_ROOM_LENGTH, description="Room to filter (optional)"),
    n_results: int = Query(5, ge=1, le=50),
    warmup: bool = Query(False),
    global_search: bool = Query(False, description="Use tunnel-based cross-room search across ALL rooms"),
    use_tunnels: bool = Query(True, description="When global_search=True, use tunnel-aware graph traversal to find related rooms")
):
    """
    Semantic search across rooms in the default wing.
    
    **Room-Based Search Architecture:**
    - **Default behavior (no wing specified):** Searches ALL rooms in the 'conversations' wing
    - **Scoped to room:** Search only in specified room
    - **Custom wing:** Specify a different wing to search
    
    **Search Modes:**
    - **Default (wing=None, room=None)**: Search all rooms in 'conversations' wing
    - **Room-scoped (room specified)**: Search only in specified room (within default wing or custom wing)
    - **Wing-scoped (wing specified)**: Search all rooms in specified wing
    - **Tunnel-aware (global_search=True, use_tunnels=True)**: 
      - Searches all rooms PLUS tunnel-connected rooms
      - If room specified: expands from that room's tunnels
      - If no room: discovers all tunnel connections
    
    **Parameters:**
    - `query`: Search query (required)
    - `wing`: Wing to search. Default: 'conversations'. None = default wing
    - `room`: Filter to specific room (optional)
    - `n_results`: Number of results per source (default 5)
    - `global_search`: Enable tunnel-aware expansion (default False)
    - `use_tunnels`: Enable tunnel graph traversal (default True)
    
    **Returns:**
    - `results`: Deduplicated and ranked results across all searched rooms
    - `latencies.per_room_ms`: Breakdown of latency per room
    - `latencies.rooms_searched`: Total rooms searched
    - `wings_searched`: List of all wings/rooms that were searched
    """
    latencies = {}
    start_total = time.perf_counter()

    # ─── Optional warmup ──────────────────────────────────
    if warmup and not app_state["embedding_model_warmed"]:
        w_start = time.perf_counter()
        if MEMPALACE_API_AVAILABLE:
            try:
                search_memories(query="warmup", palace_path=PALACE_PATH, n_results=1)
                app_state["embedding_model_warmed"] = True
            except Exception as e:
                logger.warning(f"Warmup failed: {e}")
        latencies["warmup_ms"] = round((time.perf_counter() - w_start) * 1000, 2)
    elif warmup and app_state["embedding_model_warmed"]:
        latencies["warmup_ms"] = 0.0

    tunnels_used: Optional[List[str]] = None
    
    # Determine target wing (default or specified)
    target_wing = wing or MEMPALACE_DEFAULT_WING

    # ─── Scoped search: caller specified a room ───────────
    if room is not None:
        logger.info(f"Scoped search: room={room!r} query={query!r}")
        
        # Discover all wings that contain this room
        all_available_wings = _discover_wings()
        wings_with_room = []
        
        for available_wing in all_available_wings:
            try:
                wing_rooms = _discover_rooms(available_wing)
                if room in wing_rooms:
                    wings_with_room.append(available_wing)
                    logger.info(f"Found room '{room}' in wing '{available_wing}'")
            except Exception as e:
                logger.warning(f"Could not check rooms in wing '{available_wing}': {e}")
        
        if not wings_with_room:
            # Fallback: search in target_wing if no wings were found
            logger.warning(f"Room '{room}' not found in any wing; falling back to target wing '{target_wing}'")
            wings_with_room = [target_wing]
        
        logger.info(f"Searching room '{room}' across {len(wings_with_room)} wing(s): {wings_with_room}")
        
        # Search the room across all wings that contain it
        if len(wings_with_room) == 1:
            # Single wing: direct search
            s_start = time.perf_counter()
            if MEMPALACE_API_AVAILABLE:
                parsed = _search_python_api(query, wing=wings_with_room[0], room=room, n_results=n_results)
            else:
                parsed = _search_cli(query, wing=wings_with_room[0], room=room, n_results=n_results)
            latencies["search_ms"] = round((time.perf_counter() - s_start) * 1000, 2)
            all_wings = [f"{wings_with_room[0]}:{room}"]
        else:
            # Multiple wings: cross-wing search for the same room
            search_fn = _search_python_api if MEMPALACE_API_AVAILABLE else _search_cli
            all_results, per_wing_latencies = _search_all_wings(
                query, wings_with_room, wing=None, room=room, n_results=n_results, search_fn=search_fn
            )
            parsed = _dedup_and_rank(all_results, n_results)
            latencies["per_wing_ms"] = per_wing_latencies
            latencies["wings_searched"] = len(wings_with_room)
            latencies["total_raw_results"] = len(all_results)
            latencies["unique_results"] = len(parsed)
            latencies["search_ms"] = round((time.perf_counter() - start_total) * 1000, 2)
            all_wings = [f"{w}:{room}" for w in wings_with_room]

    # ─── Multi-room search: no room specified (search all rooms in wing) ──
    else:
        # Discover all rooms in the target wing
        rooms = _discover_rooms(target_wing)
        
        # Optional tunnel expansion for global_search
        if global_search and use_tunnels:
            tunnel_connected_rooms: set = set()
            
            if room:
                # Expand via tunnels from specific room
                tunnels = _discover_tunnels(room)
                for tunnel_room, connected_rooms in tunnels.items():
                    tunnel_connected_rooms.update(connected_rooms)
                    tunnels_used = tunnels_used or []
                    tunnels_used.append(f"{tunnel_room}: {connected_rooms}")
                logger.info(f"Tunnel expansion for room={room!r}: added {len(tunnel_connected_rooms)} connected rooms")
            else:
                # Discover all tunnel connections across all rooms
                all_tunnels = _discover_tunnels()
                for tunnel_room, connected_rooms in all_tunnels.items():
                    tunnel_connected_rooms.update(connected_rooms)
                    tunnels_used = tunnels_used or []
                    tunnels_used.append(f"{tunnel_room}: {connected_rooms}")
                logger.info(f"Global tunnel discovery: added {len(tunnel_connected_rooms)} tunnel-connected rooms")
            
            if tunnel_connected_rooms:
                rooms = list(set(rooms) | tunnel_connected_rooms)
                logger.info(f"After tunnel expansion: {len(rooms)} total rooms to search: {rooms}")

        all_wings = rooms

        if not rooms:
            # No rooms discovered in wing — fall back to unscoped API/CLI call
            logger.warning(f"No rooms discovered in wing '{target_wing}'; falling back to unscoped search")
            s_start = time.perf_counter()
            if MEMPALACE_API_AVAILABLE:
                parsed = _search_python_api(query, wing=target_wing, n_results=n_results)
            else:
                parsed = _search_cli(query, wing=target_wing, n_results=n_results)
            latencies["search_ms"] = round((time.perf_counter() - s_start) * 1000, 2)
        else:
            logger.info(f"Cross-room search across {len(rooms)} rooms in wing '{target_wing}': {rooms}")
            search_fn = _search_python_api if MEMPALACE_API_AVAILABLE else _search_cli
            all_results, per_room_latencies = _search_all_wings(
                query, rooms, wing=target_wing, room=None, n_results=n_results, search_fn=search_fn
            )
            parsed = _dedup_and_rank(all_results, n_results)
            latencies["per_room_ms"] = per_room_latencies
            latencies["rooms_searched"] = len(rooms)
            latencies["total_raw_results"] = len(all_results)
            latencies["unique_results"] = len(parsed)

    latencies["total_ms"] = round((time.perf_counter() - start_total) * 1000, 2)

    return SearchResponse(
        query=query,
        results_count=len(parsed),
        latencies=latencies,
        results=parsed,
        tunnels_used=tunnels_used,
        wings_searched=all_wings if wing is None else None,
    )

# ─── CLI Search Parser (fallback) ─────────────────────────
def _parse_cli_search(stdout: str) -> List[Dict]:
    RESULT_HEADER_RE = re.compile(r"^\[(\d+)\]\s+(.+?)\s*/\s*(.+)$")
    SOURCE_RE = re.compile(r"^Source:\s*(.+)$")
    MATCH_RE = re.compile(r"^Match:\s*(.+)$")
    SCORE_RE = re.compile(r"(cosine|bm25)=(\S+)")

    results = []
    current = None
    text_lines = []

    def save():
        nonlocal current, text_lines
        if current and text_lines:
            current["text"] = " ".join(text_lines).strip()
            results.append(current)
        current = None
        text_lines = []

    for line in stdout.splitlines():
        s = line.strip()
        if not s:
            continue
        m = RESULT_HEADER_RE.match(s)
        if m:
            save()
            current = {"wing": m.group(2).strip(), "room": m.group(3).strip(), "source": "", "cosine": None, "bm25": None}
            continue
        if current is None:
            continue
        m = SOURCE_RE.match(s)
        if m:
            current["source"] = m.group(1).strip()
            continue
        m = MATCH_RE.match(s)
        if m:
            for key, val in SCORE_RE.findall(m.group(1)):
                try:
                    if key == "cosine":
                        current["cosine"] = float(val)
                    elif key == "bm25":
                        current["bm25"] = float(val)
                except ValueError:
                    pass
            continue
        if len(s) > 5 and all(c in "─═━" for c in s):
            continue
        if len(s) > 5 and all(c == "-" for c in s):
            continue
        text_lines.append(s)
    save()
    return results

@app.get("/search/raw", tags=["Search"])
async def search_raw(
    query: str = Query(..., max_length=MAX_QUERY_LENGTH),
    wing: Optional[str] = Query(None, max_length=MAX_WING_ROOM_LENGTH),
    room: Optional[str] = Query(None, max_length=MAX_WING_ROOM_LENGTH),
    n_results: int = Query(5, ge=1, le=50)
):
    if MEMPALACE_API_AVAILABLE:
        results = _search_python_api(query, wing=wing, room=room, n_results=n_results)
        return {"results": results, "api": "python", "query": query}
    else:
        import subprocess
        args = [r".venv\Scripts\mempalace.exe", "--palace", PALACE_PATH, "search", query, "--results", str(n_results)]
        if wing:
            args.extend(["--wing", wing])
        if room:
            args.extend(["--room", room])
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        return {"stdout": result.stdout, "stderr": result.stderr, "api": "cli"}

@app.post("/mine", response_model=MineResponse, tags=["Mining"])
async def mine_jsonl(
    file: UploadFile = File(...),
    room: str = Query(..., max_length=MAX_WING_ROOM_LENGTH, description="Room name (required). Conversation group identifier."),
    wing: str = Query(MEMPALACE_DEFAULT_WING, max_length=MAX_WING_ROOM_LENGTH, description="Wing name (optional, defaults to 'conversations'). Use default unless organizing across multiple wings."),
    max_items: int = Query(MAX_ITEMS_PER_UPLOAD, ge=1, le=100_000),
):
    """
    Mine a conversation file (JSONL) into a specific room.
    
    **Room-Based Storage Architecture:**
    - All conversations are stored in rooms within the default wing
    - Each file/conversation group gets its own room
    - Rooms allow fine-grained organization while maintaining single-wing storage
    
    **Parameters:**
    - `room` (required): Room identifier (e.g., "healthcare", "finance", "conversation-001")
    - `wing` (optional): Wing name. Defaults to "conversations". Override to store in different wing.
    - `file`: JSONL file to mine
    - `max_items`: Max entries to process
    
    **Example Requests:**
    - POST /mine?room=healthcare&wing=conversations ← Default wing
    - POST /mine?room=finance ← Uses default wing automatically
    - POST /mine?room=backup&wing=archive ← Custom wing
    """
    if app_state["mine_in_progress"]:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Mining in progress. POST /reset-guard to clear."
        )
    
    if not room or not room.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="room parameter cannot be empty")
    
    app_state["mine_in_progress"] = True
    try:
        import tempfile, shutil
        temp_dir = Path(tempfile.gettempdir()) / "mempalace-bench"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # Create a subdirectory named after the room to force correct routing by folder name
        room_dir = temp_dir / room
        room_dir.mkdir(parents=True, exist_ok=True)

        parse_start = time.perf_counter()
        try:
            num_files = await parse_and_save_to_text(file, room_dir, max_items=max_items)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid JSONL: {e}")
        parse_duration = (time.perf_counter() - parse_start) * 1000

        if num_files == 0:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid entries")

        mine_start = time.perf_counter()
        if MEMPALACE_API_AVAILABLE:
            try:
                mine_directory(temp_dir, palace_path=PALACE_PATH, wing=wing, room=room)
                mine_success = True
            except Exception as e:
                logger.error(f"Python API mine failed: {e}")
                mine_success = False
        else:
            import subprocess
            args = [r".venv\Scripts\mempalace.exe", "--palace", PALACE_PATH, "mine", str(temp_dir), "--wing", wing]
            if room:
                args.extend(["--room", room])
            result = subprocess.run(args, capture_output=True, text=True, timeout=300)
            mine_success = result.returncode == 0

        shutil.rmtree(temp_dir, ignore_errors=True)
        mine_duration = (time.perf_counter() - mine_start) * 1000

        if not mine_success:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Mining failed")

        # Invalidate graph cache on successful write
        if MEMPALACE_API_AVAILABLE:
            try:
                from mempalace.palace_graph import invalidate_graph_cache
                invalidate_graph_cache()
            except Exception:
                pass

        return MineResponse(
            success=True,
            message=f"Mined {num_files} conversations",
            items_processed=num_files,
            total_latency=LatencyResult(
                operation="mine",
                total_duration_ms=round(parse_duration + mine_duration, 2),
                per_item_duration_ms=round((parse_duration + mine_duration) / num_files, 2),
                item_count=num_files
            ),
            breakdown={"parse_jsonl_ms": round(parse_duration, 2), "mine_ms": round(mine_duration, 2)}
        )
    finally:
        app_state["mine_in_progress"] = False

@app.post("/mine-and-search", tags=["Pipeline"])
async def mine_and_search(
    file: UploadFile = File(...),
    room: str = Query(..., max_length=MAX_WING_ROOM_LENGTH, description="Room name (required)"),
    wing: str = Query(MEMPALACE_DEFAULT_WING, max_length=MAX_WING_ROOM_LENGTH, description="Wing name (optional, defaults to 'conversations')"),
    test_query: str = Query("global digital health market", max_length=MAX_QUERY_LENGTH),
    n_results: int = Query(5, ge=1, le=50)
):
    """
    Mine a conversation file and immediately search across all rooms.
    
    **Room-Based Pipeline:**
    1. Mine conversation file into specified room
    2. Search across all rooms in the wing
    3. Return both mining and search results
    """
    mine_resp = await mine_jsonl(file, room=room, wing=wing)
    search_resp = await search_palace(query=test_query, wing=wing, room=room, n_results=n_results)
    return {
        "pipeline": "mine → search",
        "file": file.filename,
        "wing": wing,
        "room": room,
        "mine": {
            "items_processed": mine_resp.items_processed,
            "total_ms": mine_resp.total_latency.total_duration_ms,
            "per_item_ms": mine_resp.total_latency.per_item_duration_ms
        },
        "search": {
            "query": test_query,
            "latency_ms": search_resp.latencies.get("search_ms", 0),
            "results_count": search_resp.results_count,
            "results": search_resp.results[:n_results]
        }
    }

@app.get("/status", tags=["System"])
async def palace_status():
    if MEMPALACE_API_AVAILABLE and app_state["memory_stack"] is not None:
        try:
            stats = app_state["memory_stack"].status()
            return {"source": "python_api", "stats": stats, "palace_path": PALACE_PATH}
        except Exception as e:
            logger.warning(f"Python API status failed: {e}")

    import subprocess
    result = subprocess.run([r".venv\Scripts\mempalace.exe", "--palace", PALACE_PATH, "status"], capture_output=True, text=True, timeout=10)
    has_palace = "No palace found" not in result.stdout
    return {
        "source": "cli",
        "output": result.stdout,
        "cli_returned_success": result.returncode == 0,
        "palace_exists": has_palace,
        "palace_path": PALACE_PATH
    }

@app.get("/wake-up", tags=["Memory Stack"])
async def wake_up(wing: Optional[str] = Query(None, max_length=MAX_WING_ROOM_LENGTH)):
    if MEMPALACE_API_AVAILABLE and app_state["memory_stack"] is not None:
        try:
            context = app_state["memory_stack"].wake_up(wing=wing)
            return {"context": context, "source": "python_api", "wing": wing}
        except Exception as e:
            logger.warning(f"Python API wake-up failed: {e}")

    import subprocess
    args = [r".venv\Scripts\mempalace.exe", "--palace", PALACE_PATH, "wake-up"]
    if wing:
        args.extend(["--wing", wing])
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    return {"context": result.stdout, "source": "cli", "wing": wing}

@app.post("/compress", tags=["Maintenance"])
async def compress_palace(wing: Optional[str] = Query(None, max_length=MAX_WING_ROOM_LENGTH)):
    import subprocess
    args = [r".venv\Scripts\mempalace.exe", "--palace", PALACE_PATH, "compress"]
    if wing:
        args.extend(["--wing", wing])
    result = subprocess.run(args, capture_output=True, text=True, timeout=300)
    return {"success": result.returncode == 0, "output": result.stdout, "stderr": result.stderr}

@app.post("/repair", tags=["Maintenance"])
async def repair_palace():
    import subprocess
    result = subprocess.run([r".venv\Scripts\mempalace.exe", "--palace", PALACE_PATH, "repair"], capture_output=True, text=True, timeout=300)
    return {"success": result.returncode == 0, "output": result.stdout, "stderr": result.stderr}

@app.post("/reset-guard", tags=["System"])
async def reset_mine_guard():
    was_stuck = app_state["mine_in_progress"]
    app_state["mine_in_progress"] = False
    return {"was_stuck": was_stuck, "guard_reset": True}

# ─── Main ───────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
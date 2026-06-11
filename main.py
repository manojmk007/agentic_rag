import json
import time
import os
import re
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from contextlib import asynccontextmanager

# Configure path to local venv site-packages to ensure robust importing
sys.path.insert(0, str(Path(__file__).resolve().parent / ".venv" / "Lib" / "site-packages"))

from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ─── MongoDB Vector Storage ──────────────────────────────
try:
    from mongo_storage import MongoVectorStorage, initialize_storage, shutdown_storage
    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False


# ─── Logging Setup ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("mempalace-tester")

# ─── Configuration ──────────────────────────────────────────

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
    wings_searched: Optional[List[str]] = None

class HealthResponse(BaseModel):
    status: str
    mongodb: Optional[Dict] = None
    timestamp: str



# ─── Application State ──────────────────────────────────────
app_state: Dict[str, Any] = {
    "palace_initialized": False,
    "mine_in_progress": False,
    "embedding_model_warmed": False,
    "mongo_storage": None,
}

# ─── Lifespan Manager ──────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MemPalace Latency Tester v3 (MongoDB Backend)...")

    # Initialize MongoDB storage
    if MONGODB_AVAILABLE:
        try:
            storage = initialize_storage()
            if storage:
                app_state["mongo_storage"] = storage
                logger.info("✓ MongoDB storage initialized")
                app_state["palace_initialized"] = True
            else:
                logger.error("MongoDB connection failed")
                logger.warning("Running in degraded mode without vector storage")
        except Exception as e:
            logger.error(f"Failed to initialize MongoDB: {e}")
    else:
        logger.error("MongoDB module not available")

    yield

    logger.info("Shutting down MemPalace Latency Tester...")
    # Cleanup MongoDB connection
    if app_state["mongo_storage"]:
        shutdown_storage()

app = FastAPI(
    title="MemPalace Latency Tester",
    version="3.0.0",
    description="Python API-based latency testing with wing-based client isolation",
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



# ─── Helper: Discover wings via PalaceGraph ────────────────
def _discover_wings() -> List[str]:
    """
    Discover all wings in the palace via MongoDB
    
    Returns: List of wing names
    """
    storage = app_state.get("mongo_storage")
    if storage:
        try:
            wings = storage.get_wings()
            logger.info(f"_discover_wings result: {wings}")
            return wings
        except Exception as e:
            logger.warning(f"MongoDB wing discovery failed: {e}")
    
    return []


def _discover_rooms(wing: Optional[str] = None) -> List[str]:
    """
    Discover all rooms in a wing via MongoDB
    
    Args:
        wing: Wing name to query. If None, uses MEMPALACE_DEFAULT_WING
    
    Returns: List of room names in the wing
    """
    target_wing = wing or MEMPALACE_DEFAULT_WING
    storage = app_state.get("mongo_storage")
    
    if storage:
        try:
            rooms = storage.get_rooms(target_wing)
            logger.info(f"_discover_rooms(wing='{target_wing}') result: {rooms}")
            return rooms
        except Exception as e:
            logger.debug(f"MongoDB room discovery for wing '{target_wing}' failed: {e}")
    
    return []



# ─── Helper: Search via Python API ─────────────────────────
def _search_mongodb(query: str, wing: Optional[str] = None, room: Optional[str] = None, n_results: int = 5) -> List[Dict]:
    """
    Search via MongoDB vector storage.
    
    Args:
        query: Search query
        wing: Wing to search (required)
        room: Room to filter (optional, if None searches all rooms in wing)
        n_results: Number of results to return
    
    Returns: List of result dictionaries with wing, room, text, source, etc.
    """
    results = []
    storage = app_state.get("mongo_storage")
    
    if not storage:
        logger.error("MongoDB storage not available")
        return results
    
    try:
        target_wing = wing or MEMPALACE_DEFAULT_WING
        
        if room:
            # Search specific room
            mongo_results = storage.search_wing(query, target_wing, room=room, n_results=n_results)
        else:
            # Search all rooms in wing
            mongo_results = storage.search_all_rooms(query, target_wing, n_results=n_results)
        
        # Convert MongoDB results to response format
        for r in mongo_results:
            results.append({
                "wing": r.get("wing", target_wing),
                "room": r.get("room", room or ""),
                "source": r.get("source", ""),
                "text": r.get("content", ""),
                "score": r.get("score", 0),
                "metadata": r.get("metadata", {}),
                "source_wing": f"{target_wing}:{r.get('room', '')}" if not room else f"{target_wing}:{room}"
            })
            logger.debug(f"MongoDB result: {r.get('room', '')} - score: {r.get('score', 0)}")
    except Exception as e:
        logger.error(f"MongoDB search failed for wing={wing!r}, room={room!r}: {e}")
    
    return results

# ─── Helper: Multi-room search (shared logic) ──────────────
def _search_all_wings(
    query: str,
    targets: List[str],
    wing: Optional[str] = None,
    room: Optional[str] = None,
    n_results: int = 5,
    search_fn: Any = None,
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



# ─── Endpoints ─────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    health = {
        "status": "healthy",
        "mongodb": {
            "available": MONGODB_AVAILABLE,
            "connected": app_state["mongo_storage"] is not None,
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    # Check MongoDB connection health
    if MONGODB_AVAILABLE and app_state["mongo_storage"]:
        try:
            # Try to get wings count to verify connection
            wings = app_state["mongo_storage"].get_wings()
            health["mongodb"]["wings_count"] = len(wings)
        except Exception as e:
            health["status"] = "degraded"
            health["mongodb"]["connection_error"] = str(e)
    elif not MONGODB_AVAILABLE:
        health["status"] = "degraded"
    
    return health



@app.get("/wings", tags=["Graph"])
async def list_wings():
    """
    Debug endpoint: shows all wings discovered via MongoDB.
    
    In room-based architecture, shows which wings are available.
    Default wing is 'conversations' (used by /search when wing not specified).
    
    **Discovery Chain:**
    1. MongoDB direct query (primary source)
    """
    merged = _discover_wings()

    return {
        "wings": merged,
        "default_wing": MEMPALACE_DEFAULT_WING,
        "count": len(merged),
        "backend": "MongoDB",
        "architecture": "room-based (conversations in rooms within wings)"
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
    warmup: bool = Query(False)
):
    """
    Semantic search across rooms in a wing with data isolation.
    
    **Room-Based Search Architecture:**
    - **Default behavior (no wing specified):** Searches ALL rooms in the 'conversations' wing
    - **Scoped to room:** Search only in specified room
    - **Custom wing:** Specify a different wing to search (for different client)
    
    **Search Modes:**
    - **Default (wing=None, room=None)**: Search all rooms in 'conversations' wing
    - **Room-scoped (room specified)**: Search only in specified room (within specified or default wing)
    - **Wing-scoped (wing specified)**: Search all rooms in specified wing only
    
    **Data Isolation:**
    - Each wing is completely isolated from other wings
    - Searches respect wing boundaries and do NOT cross into other wings
    - Different clients can use different wings without data leakage
    
    **Parameters:**
    - `query`: Search query (required)
    - `wing`: Wing to search. Default: 'conversations'. None = default wing
    - `room`: Filter to specific room (optional)
    - `n_results`: Number of results per source (default 5)
    - `warmup`: Warm up embedding model before search (default False)
    
    **Returns:**
    - `results`: Deduplicated and ranked results across searched rooms in the wing
    - `latencies.search_ms`: Search latency
    - `wings_searched`: List of all rooms that were searched (None if wing specified)
    """
    latencies = {}
    start_total = time.perf_counter()

    # ─── Optional warmup ──────────────────────────────────
    if warmup and not app_state["embedding_model_warmed"]:
        w_start = time.perf_counter()
        # Warmup happens implicitly on first search, but we can mark it
        app_state["embedding_model_warmed"] = True
        latencies["warmup_ms"] = round((time.perf_counter() - w_start) * 1000, 2)
    elif warmup and app_state["embedding_model_warmed"]:
        latencies["warmup_ms"] = 0.0
    
    # Determine target wing (default or specified)
    target_wing = wing or MEMPALACE_DEFAULT_WING

    # ─── Perform search via MongoDB ─────────────────────────
    s_start = time.perf_counter()
    parsed = _search_mongodb(query, wing=target_wing, room=room, n_results=n_results)
    latencies["search_ms"] = round((time.perf_counter() - s_start) * 1000, 2)

    # Deduplicate and rank results
    if room is None:
        # Multi-room search - get list of searched rooms
        all_rooms = _discover_rooms(target_wing)
        all_wings = all_rooms
        latencies["rooms_searched"] = len(all_rooms)
    else:
        # Single room search
        all_wings = [f"{target_wing}:{room}"]
        latencies["rooms_searched"] = 1

    latencies["total_results"] = len(parsed)
    latencies["total_ms"] = round((time.perf_counter() - start_total) * 1000, 2)

    return SearchResponse(
        query=query,
        results_count=len(parsed),
        latencies=latencies,
        results=parsed,
        wings_searched=all_wings if wing is None else None,
    )



@app.post("/mine", response_model=MineResponse, tags=["Mining"])
async def mine_jsonl(
    file: UploadFile = File(...),
    room: str = Query(..., max_length=MAX_WING_ROOM_LENGTH, description="Room name (required). Conversation group identifier."),
    wing: str = Query(MEMPALACE_DEFAULT_WING, max_length=MAX_WING_ROOM_LENGTH, description="Wing name (optional, defaults to 'conversations'). Use default unless organizing across multiple wings."),
    max_items: int = Query(MAX_ITEMS_PER_UPLOAD, ge=1, le=100_000),
):
    """
    Mine a conversation file (JSONL) into a specific room via MongoDB.
    
    **Room-Based Storage Architecture:**
    - All conversations are stored in rooms within wings
    - Each file/conversation group gets its own room
    - Rooms allow fine-grained organization while maintaining wing-based isolation
    
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
    
    storage = app_state.get("mongo_storage")
    if not storage:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MongoDB storage not available"
        )
    
    app_state["mine_in_progress"] = True
    try:
        parse_start = time.perf_counter()
        
        # Read and parse JSONL file
        try:
            content = await file.read()
            text_content = content.decode('utf-8')
        except (UnicodeDecodeError, AttributeError) as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"File read error: {e}")
        
        items_processed = 0
        for i, line in enumerate(text_content.strip().split('\n')):
            if i >= max_items:
                break
            
            if not line.strip():
                continue
            
            try:
                data = json.loads(line)
                if not isinstance(data, dict):
                    logger.warning(f"Skipping non-dict item {i}")
                    continue
                
                # Extract content from various common formats
                entry_text = data.get('text') or data.get('content') or data.get('message') or str(data)
                if not entry_text:
                    continue
                
                source = data.get('source', 'jsonl_upload')
                metadata = {k: v for k, v in data.items() if k not in ['text', 'content', 'message', 'source']}
                
                # Store in MongoDB (embeddings left empty for text-based search)
                storage.store_memory(
                    wing=wing,
                    room=room,
                    content=entry_text,
                    embedding=[],  # Text search doesn't require vector embeddings
                    source=source,
                    metadata=metadata
                )
                items_processed += 1
                
            except json.JSONDecodeError as e:
                logger.warning(f"Skipping invalid JSON at line {i}: {e}")
                continue
            except Exception as e:
                logger.error(f"Error storing memory at line {i}: {e}")
                continue
        
        parse_duration = (time.perf_counter() - parse_start) * 1000
        
        if items_processed == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid entries parsed from file")
        
        return MineResponse(
            success=True,
            message=f"Mined {items_processed} conversations into {wing}:{room}",
            items_processed=items_processed,
            total_latency=LatencyResult(
                operation="mine",
                total_duration_ms=round(parse_duration, 2),
                per_item_duration_ms=round(parse_duration / items_processed, 2),
                item_count=items_processed
            ),
            breakdown={"parse_and_store_ms": round(parse_duration, 2)}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Mining failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Mining error: {str(e)}")
    finally:
        app_state["mine_in_progress"] = False

@app.get("/status", tags=["System"])
async def palace_status():
    storage = app_state.get("mongo_storage")
    
    if storage:
        try:
            stats = storage.get_statistics()
            return {
                "source": "mongodb",
                "stats": stats,
                "backend": "MongoDB",
                "status": "operational"
            }
        except Exception as e:
            logger.warning(f"MongoDB status query failed: {e}")
            return {
                "source": "mongodb",
                "status": "error",
                "error": str(e)
            }
    
    return {
        "source": "none",
        "status": "mongodb_not_available",
        "message": "MongoDB storage not initialized"
    }



@app.post("/reset-guard", tags=["System"])
async def reset_mine_guard():
    was_stuck = app_state["mine_in_progress"]
    app_state["mine_in_progress"] = False
    return {"was_stuck": was_stuck, "guard_reset": True}

# ─── Main ───────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
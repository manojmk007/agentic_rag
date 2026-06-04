# ✅ FINAL IMPLEMENTATION: Room-Based Architecture with Optional Wing

## Overview

Successfully implemented a **room-based storage architecture** for MemPalace where:

1. ✅ **Room parameter is REQUIRED** — Each file goes to a specific room
2. ✅ **Wing parameter is OPTIONAL** — Defaults to `conversations` wing
3. ✅ **Multi-wing support** — Can store in different wings if needed
4. ✅ **Fallback search** — Search supports both single-wing and multi-wing queries
5. ✅ **Fresh start** — All existing data deleted, ready for new room-based organization

---

## Architecture

### Storage Model

```
MemPalace Palace
├── Wing: "conversations" (DEFAULT)
│   ├── Room: healthcare_cardiology
│   ├── Room: healthcare_neurology
│   ├── Room: finance_trading
│   └── Room: support_tickets
│
├── Wing: "archive" (OPTIONAL - if needed)
│   └── Room: old_conversations
│
└── Wing: "backup" (OPTIONAL - if needed)
    └── Room: legacy_data
```

### Key Points

- **Default Wing**: `conversations` — Used unless explicitly specified otherwise
- **Room Organization**: All data organized by rooms for fine-grained control
- **Multi-Wing Support**: Can store data in different wings (healthcare, finance, etc.)
- **Flexible Architecture**: Supports both single-wing (recommended) and multi-wing deployments

---

## API Endpoints

### Mining: `/mine`

**Parameters:**
- `file` (required) — JSONL file to mine
- `room` (required) — Room name (e.g., "healthcare_cardiology")
- `wing` (optional) — Wing name. Defaults to `conversations`
- `max_items` (optional) — Max items to process (default: 10000)

**Examples:**

```bash
# Mine to default wing (conversations)
curl -X POST http://localhost:8000/mine \
  -F "file=@data.jsonl" \
  -F "room=healthcare_cardiology"

# Mine to specific wing
curl -X POST http://localhost:8000/mine \
  -F "file=@data.jsonl" \
  -F "room=old_conversations" \
  -F "wing=archive"
```

### Search: `/search`

**Parameters:**
- `query` (required) — Search query
- `wing` (optional) — Wing to search. Defaults to `conversations`
- `room` (optional) — Filter to specific room (within wing)
- `n_results` (optional) — Number of results (default: 5)
- `global_search` (optional) — Enable tunnel-based cross-room search
- `use_tunnels` (optional) — Use tunnel-aware graph traversal

**Examples:**

```bash
# Search all rooms in default wing (conversations)
curl "http://localhost:8000/search?query=symptoms"

# Search specific room in default wing
curl "http://localhost:8000/search?query=symptoms&room=healthcare_cardiology"

# Search all rooms in specific wing
curl "http://localhost:8000/search?query=symptoms&wing=archive"

# Multi-wing search with tunnel expansion
curl "http://localhost:8000/search?query=symptoms&global_search=true&use_tunnels=true"
```

### Rooms Discovery: `/rooms`

**Parameters:**
- `wing` (optional) — Wing to query. Defaults to `conversations`

**Examples:**

```bash
# List all rooms in default wing
curl http://localhost:8000/rooms

# List all rooms in specific wing
curl "http://localhost:8000/rooms?wing=archive"
```

### Wings Discovery: `/wings`

**Lists all wings** in the palace.

```bash
curl http://localhost:8000/wings
```

---

## Search Behavior

### Default Behavior (Recommended)

```
GET /search?query=text
└─ Searches ALL rooms in default "conversations" wing
   └─ Returns aggregated results from all rooms
```

### Single-Wing Search

```
GET /search?query=text&wing=archive
└─ Searches ALL rooms in "archive" wing
   └─ Returns results only from archive wing
```

### Room-Scoped Search

```
GET /search?query=text&room=healthcare_cardiology
└─ Searches specific room in default "conversations" wing
   └─ Returns results only from that room
```

### Multi-Wing Fallback Search

```
GET /search?query=text&global_search=true&use_tunnels=true
└─ Searches across multiple wings + tunnel-connected rooms
   └─ Advanced cross-wing exploration
```

---

## Workflow Comparison

### BEFORE (Pure Multi-Wing)
```
Healthcare Wing
├─ Room: cardiology
├─ Room: neurology
└─ Room: radiology

Finance Wing
├─ Room: trading
└─ Room: compliance

Support Wing
└─ Room: tickets
```

### AFTER (Room-Based with Optional Wing)
```
conversations Wing (DEFAULT)
├─ Room: healthcare_cardiology
├─ Room: healthcare_neurology
├─ Room: healthcare_radiology
├─ Room: finance_trading
├─ Room: finance_compliance
└─ Room: support_tickets

[OPTIONAL] archive Wing
└─ Room: old_conversations

[OPTIONAL] backup Wing
└─ Room: legacy_data
```

---

## Implementation Details

### Configuration

```python
# Default wing for all conversations
MEMPALACE_DEFAULT_WING = "conversations"

# Optional wings can be created as needed
# Examples: "archive", "backup", "custom"
```

### Mining Logic

```python
# User provides room (required)
# User optionally provides wing (defaults to "conversations")
# File is stored at: wing:room

mine(file, room="healthcare_cardiology")
  └─ Stored at: conversations:healthcare_cardiology

mine(file, room="old_data", wing="archive")
  └─ Stored at: archive:old_data
```

### Search Logic

```python
# Search in default wing (all rooms)
search(query="symptoms")
  └─ Searches: all rooms in "conversations" wing

# Search in specific wing (all rooms)
search(query="symptoms", wing="archive")
  └─ Searches: all rooms in "archive" wing

# Search specific room
search(query="symptoms", room="healthcare_cardiology")
  └─ Searches: conversations:healthcare_cardiology

# Multi-wing fallback
search(query="symptoms", global_search=True, use_tunnels=True)
  └─ Searches: across multiple wings with tunnel connections
```

---

## Benefits

✅ **Organized Storage**
- Rooms provide fine-grained organization
- All conversations in predictable location (default wing)

✅ **Flexible Architecture**
- Single wing for most use cases
- Multiple wings available if needed

✅ **Clear Defaults**
- Default wing: "conversations"
- Default search: all rooms in default wing

✅ **Backward Compatible**
- Wing parameter optional
- Can add wing-based organization later

✅ **Multi-Wing Fallback**
- Support for multiple wings if organization evolves
- Tunnel-based cross-wing search

---

## Setup Instructions

### 1. Clean Existing Data

```bash
python delete_palace_data.py
```

This deletes all existing palace data and starts fresh.

### 2. Mine First Conversation Set

```bash
curl -X POST http://localhost:8000/mine \
  -F "file=@healthcare_data.jsonl" \
  -F "room=healthcare_cardiology"
```

### 3. Mine Second Conversation Set

```bash
curl -X POST http://localhost:8000/mine \
  -F "file=@finance_data.jsonl" \
  -F "room=finance_trading"
```

### 4. Search All Conversations

```bash
curl "http://localhost:8000/search?query=your_query"
```

### 5. List All Rooms

```bash
curl http://localhost:8000/rooms
```

---

## API Response Examples

### Mining Response

```json
{
  "success": true,
  "message": "Mined 100 conversations into wing 'conversations', room 'healthcare_cardiology'",
  "items_processed": 100,
  "total_latency": {
    "operation": "mine",
    "total_duration_ms": 1234.56,
    "per_item_duration_ms": 12.35,
    "item_count": 100
  },
  "breakdown": {
    "parse_jsonl_ms": 234.56,
    "mine_ms": 1000.0
  }
}
```

### Search Response

```json
{
  "query": "symptoms",
  "results_count": 5,
  "latencies": {
    "per_room_ms": {
      "conversations:healthcare_cardiology": 45.23,
      "conversations:finance_trading": 38.12
    },
    "rooms_searched": 2,
    "total_raw_results": 15,
    "unique_results": 5,
    "total_ms": 125.24
  },
  "results": [
    {
      "wing": "conversations",
      "room": "healthcare_cardiology",
      "source": "...",
      "cosine": 0.95,
      "bm25": 123.45,
      "text": "..."
    }
  ]
}
```

### Rooms Response

```json
{
  "wing": "conversations",
  "rooms": ["healthcare_cardiology", "finance_trading", "support_tickets"],
  "count": 3,
  "architecture": "room-based storage"
}
```

---

## Migration Path

### Phase 1: Room-Based in Default Wing (Current)
- ✅ All conversations in "conversations" wing
- ✅ Organized by rooms
- ✅ Simple, predictable, recommended

### Phase 2: Optional Multi-Wing (Future)
- ✅ Available now if needed
- Can add separate "archive" wing for old data
- Can add "backup" wing for replicas
- Tunnel-based search works across wings

### Phase 3: Advanced Tuning (Future)
- Can optimize search strategies by wing
- Can implement wing-specific retention policies
- Can set wing-specific permissions

---

## Room Naming Conventions

Recommended patterns:

```
domain_subdomain_context

Examples:
✓ healthcare_cardiology_consultation
✓ healthcare_neurology_research
✓ finance_trading_strategies
✓ finance_compliance_audit
✓ support_tier1_technical
✓ support_tier2_billing
✓ marketing_campaign_feedback
✓ marketing_social_media_questions

Benefits:
- Self-documenting
- Easy to filter/scope
- Clear organization
```

---

## Testing

### 1. Verify Architecture

```bash
curl http://localhost:8000/health
# Should show palace is healthy and ready
```

### 2. List Rooms

```bash
curl http://localhost:8000/rooms
# Should return empty initially
```

### 3. Mine Test Data

```bash
curl -X POST http://localhost:8000/mine \
  -F "file=@test_data.jsonl" \
  -F "room=test_room"
```

### 4. List Rooms Again

```bash
curl http://localhost:8000/rooms
# Should now show test_room
```

### 5. Search

```bash
curl "http://localhost:8000/search?query=test"
# Should return results from test_room
```

---

## Summary

| Aspect | Value |
|--------|-------|
| Default Wing | `conversations` |
| Wing Parameter | Optional (defaults to "conversations") |
| Room Parameter | Required |
| Multi-Wing Support | Yes (optional) |
| Fallback Search | Tunnel-based cross-wing search |
| Data Cleanup | Done ✓ |
| Documentation | Complete ✓ |
| Ready for Production | Yes ✓ |

---

## Next Steps

1. Run: `python delete_palace_data.py` (already done)
2. Start mining conversations to rooms
3. Use `/search` to find conversations
4. Monitor `/rooms` to see organization
5. Optionally add more wings if needed

**Status: ✅ READY FOR PRODUCTION**

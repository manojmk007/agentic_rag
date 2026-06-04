# 🚀 Quick Migration Guide: Room-Based Architecture

## What Changed?

The MemPalace API now uses a **room-based architecture** with optional wing support:

```
✓ Room parameter: REQUIRED (e.g., healthcare_cardiology)
✓ Wing parameter: OPTIONAL (defaults to "conversations")
✓ Multi-wing support: Available as fallback
✓ Fresh start: All data deleted, starting clean
```

---

## Before vs After

### Mining Data

**BEFORE (Multiple Separate Wings):**
```bash
curl -X POST /mine -F "file=healthcare.jsonl" -F "wing=healthcare" -F "room=cardiology"
curl -X POST /mine -F "file=finance.jsonl" -F "wing=finance" -F "room=trading"
```

**AFTER (Room-Based with Default Wing):**
```bash
# Uses default "conversations" wing automatically
curl -X POST /mine -F "file=healthcare.jsonl" -F "room=healthcare_cardiology"
curl -X POST /mine -F "file=finance.jsonl" -F "room=finance_trading"

# Or explicitly specify wing if needed
curl -X POST /mine -F "file=old.jsonl" -F "room=legacy" -F "wing=archive"
```

### Searching Data

**BEFORE:**
```bash
# Had to specify which wing to search
curl "/search?query=symptoms&wing=healthcare"
curl "/search?query=price&wing=finance"
```

**AFTER:**
```bash
# Default search across all rooms in "conversations" wing
curl "/search?query=symptoms"

# Or specify wing if using multi-wing approach
curl "/search?query=old_query&wing=archive"

# Or scope to specific room
curl "/search?query=symptoms&room=healthcare_cardiology"
```

---

## Key Parameters

### Mining (`POST /mine`)

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file` | File | Yes | N/A | JSONL file to mine |
| `room` | String | Yes | N/A | Room identifier (e.g., "healthcare_cardiology") |
| `wing` | String | No | "conversations" | Wing name (override default if needed) |
| `max_items` | Integer | No | 10000 | Max items to process |

### Search (`GET /search`)

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | String | Yes | N/A | Search query |
| `wing` | String | No | "conversations" | Wing to search |
| `room` | String | No | None | Optional room filter |
| `n_results` | Integer | No | 5 | Number of results |
| `global_search` | Boolean | No | false | Enable cross-wing search |
| `use_tunnels` | Boolean | No | true | Use tunnel connections |

---

## Common Use Cases

### Single Domain (Recommended)

**Store all conversations in default wing, organized by room:**

```bash
# Healthcare conversations
curl -X POST /mine -F "file=health1.jsonl" -F "room=healthcare_cardiology"
curl -X POST /mine -F "file=health2.jsonl" -F "room=healthcare_neurology"

# Finance conversations
curl -X POST /mine -F "file=fin1.jsonl" -F "room=finance_trading"
curl -X POST /mine -F "file=fin2.jsonl" -F "room=finance_compliance"

# Search all
curl "/search?query=query"

# Or search specific domain
curl "/search?query=query&room=healthcare_cardiology"
```

### Multi-Wing Organization (Advanced)

**Use different wings for different purposes:**

```bash
# Current conversations in default wing
curl -X POST /mine -F "file=current.jsonl" -F "room=active_conversations"

# Archive old conversations in separate wing
curl -X POST /mine -F "file=old.jsonl" -F "room=old_data" -F "wing=archive"

# Search current wing
curl "/search?query=query"

# Search archive wing
curl "/search?query=query&wing=archive"

# Search all with tunnel expansion
curl "/search?query=query&global_search=true"
```

---

## Important Notes

### Room Naming

Use meaningful names with context:

```
✓ healthcare_cardiology      (domain_subdomain)
✓ finance_trading_strategies  (domain_subdomain_context)
✓ support_tier1_technical     (domain_level_type)

✗ room1, room2               (not descriptive)
✗ data_123                   (no context)
```

### Default Wing

Most use cases should use the default wing:

```bash
# Recommended: Let it use default wing
curl -X POST /mine -F "file=data.jsonl" -F "room=my_room"

# Only if organizing across multiple wings:
curl -X POST /mine -F "file=old.jsonl" -F "room=old_data" -F "wing=archive"
```

### Cleanup Script

Before starting, clean up old data:

```bash
python delete_palace_data.py
```

---

## Step-by-Step Setup

### Step 1: Clean Old Data
```bash
python delete_palace_data.py
```

### Step 2: Mine First Dataset
```bash
curl -X POST http://localhost:8000/mine \
  -F "file=@data1.jsonl" \
  -F "room=room1"
```

### Step 3: Mine Second Dataset
```bash
curl -X POST http://localhost:8000/mine \
  -F "file=@data2.jsonl" \
  -F "room=room2"
```

### Step 4: List Rooms
```bash
curl http://localhost:8000/rooms
```

### Step 5: Search
```bash
curl "http://localhost:8000/search?query=your_query"
```

---

## Troubleshooting

### Q: Do I need to specify wing?
**A:** No! It defaults to "conversations". Only specify if organizing across multiple wings.

### Q: Can I still use multiple wings?
**A:** Yes! Just pass `wing=custom_wing` in mining and searching.

### Q: How do I migrate old data?
**A:** Use room names with domain prefixes (e.g., "healthcare_cardiology" instead of separate wings).

### Q: What's the difference between room and wing?
**A:** 
- **Wing**: Top-level grouping (usually one, "conversations")
- **Room**: Fine-grained organization within wing

### Q: Should I use the default wing?
**A:** Yes, unless you need to organize data across multiple wings.

---

## API Quick Reference

```bash
# Mine to default wing
POST /mine?file=data.jsonl&room=room_name

# Mine to custom wing
POST /mine?file=data.jsonl&room=room_name&wing=custom_wing

# Search all in default wing
GET /search?query=text

# Search specific room
GET /search?query=text&room=room_name

# Search custom wing
GET /search?query=text&wing=custom_wing

# List rooms in default wing
GET /rooms

# List rooms in custom wing
GET /rooms?wing=custom_wing

# List all wings
GET /wings

# Check health
GET /health
```

---

## Status ✅

| Item | Status |
|------|--------|
| Architecture | ✅ Room-based with optional wing |
| Room Parameter | ✅ Required |
| Wing Parameter | ✅ Optional (defaults to "conversations") |
| Multi-Wing Support | ✅ Available |
| Data Cleanup | ✅ Ready (use delete_palace_data.py) |
| Documentation | ✅ Complete |
| Production Ready | ✅ Yes |

---

**Ready to start! Begin with Step 1 above.** 🚀

# Quick Start Guide: New Room-Based Architecture

## TL;DR

**Everything is now in the `conversations` wing. Organize conversations by room instead of by wing.**

---

## Basic Workflows

### 1. Mine Conversations

```bash
# Upload conversations to a specific room
curl -X POST http://localhost:8000/mine \
  -F "file=@conversations.jsonl" \
  -F "room=support_tickets"

# Response:
{
  "success": true,
  "message": "Mined 100 conversations into room 'support_tickets' (wing: 'conversations')",
  "items_processed": 100
}
```

**Important:** Always provide a meaningful room name (e.g., `support_tickets`, `healthcare_cardiology`, `finance_trading`)

---

### 2. List All Rooms

```bash
# Get all rooms in conversations wing
curl http://localhost:8000/rooms

# Response:
{
  "wing": "conversations",
  "rooms": ["support_tickets", "billing_inquiries", "technical_support"],
  "count": 3,
  "architecture": "room-based"
}
```

---

### 3. Search All Conversations

```bash
# Search across ALL rooms in conversations wing
curl "http://localhost:8000/search?query=refund&n_results=5"

# Response:
{
  "query": "refund",
  "results_count": 5,
  "latencies": {
    "per_room_ms": {
      "conversations:support_tickets": 45.23,
      "conversations:billing_inquiries": 38.12,
      "conversations:technical_support": 41.89
    },
    "rooms_searched": 3,
    "total_ms": 125.24
  },
  "results": [...]
}
```

---

### 4. Search Specific Room

```bash
# Search only in support_tickets room
curl "http://localhost:8000/search?query=refund&room=support_tickets&n_results=5"

# Response:
{
  "query": "refund",
  "results_count": 5,
  "latencies": {
    "search_ms": 45.23,
    "total_ms": 46.12
  },
  "results": [...]
}
```

---

## Common Tasks

### Mining Multiple Datasets

```bash
# Mine healthcare cardiology conversations
curl -X POST http://localhost:8000/mine \
  -F "file=@cardiology_data.jsonl" \
  -F "room=healthcare_cardiology"

# Mine healthcare neurology conversations
curl -X POST http://localhost:8000/mine \
  -F "file=@neurology_data.jsonl" \
  -F "room=healthcare_neurology"

# Mine finance trading conversations
curl -X POST http://localhost:8000/mine \
  -F "file=@finance_data.jsonl" \
  -F "room=finance_trading"
```

Result: All stored in `conversations` wing, organized by room.

---

### Searching Across Domains

```bash
# Search all conversations (default)
curl "http://localhost:8000/search?query=urgent"

# Search only healthcare
curl "http://localhost:8000/search?query=urgent&room=healthcare_cardiology"
curl "http://localhost:8000/search?query=urgent&room=healthcare_neurology"

# Search only finance
curl "http://localhost:8000/search?query=urgent&room=finance_trading"
```

---

## Important Changes from Old System

### ❌ DON'T DO THIS (Old Wing-Based Way)

```bash
# These won't work anymore:

curl -X POST http://localhost:8000/mine \
  -F "wing=healthcare" \
  -F "room=cardiology"  # Missing room name

curl "http://localhost:8000/search?query=text&wing=healthcare"
# wing parameter no longer recognized
```

### ✅ DO THIS (New Room-Based Way)

```bash
# Always specify room (wing is implicit: conversations)
curl -X POST http://localhost:8000/mine \
  -F "room=healthcare_cardiology"

# Search is always in conversations wing, optionally scope by room
curl "http://localhost:8000/search?query=text"  # All rooms
curl "http://localhost:8000/search?query=text&room=healthcare_cardiology"  # Specific room
```

---

## Room Naming Conventions

Recommended naming patterns for rooms:

```
domain_subdomain_purpose

Examples:
- healthcare_cardiology_consultation
- healthcare_neurology_research
- finance_trading_strategies
- finance_compliance_audit
- support_tier1_technical
- support_tier2_billing
- marketing_campaign_feedback
- marketing_social_media_questions
```

Benefits:
- Clear what data is in each room
- Easy to filter/scope searches
- Self-documenting

---

## API Reference (Room-Based)

### POST /mine
Mine conversations into a room

**Parameters:**
- `file` (required): JSONL file with conversations
- `room` (required): Room name
- `max_items` (optional): Max items to process (default: 10000)

**Example:**
```bash
curl -X POST http://localhost:8000/mine \
  -F "file=@data.jsonl" \
  -F "room=my_room"
```

---

### GET /rooms
List all rooms in conversations wing

**Parameters:** None

**Example:**
```bash
curl http://localhost:8000/rooms
```

---

### GET /search
Search conversations in rooms

**Parameters:**
- `query` (required): Search query
- `room` (optional): Specific room to search
- `n_results` (optional): Number of results (default: 5, max: 50)
- `warmup` (optional): Warm up embedding model
- `global_search` (optional): Global search flag

**Examples:**
```bash
# Search all rooms
curl "http://localhost:8000/search?query=bug"

# Search specific room
curl "http://localhost:8000/search?query=bug&room=support_tier1_technical"

# More results
curl "http://localhost:8000/search?query=bug&n_results=20"
```

---

### GET /health
Check API health and architecture

**Example:**
```bash
curl http://localhost:8000/health
```

**Response includes:**
```json
{
  "status": "healthy",
  "architecture": "room-based",
  "default_wing": "conversations"
}
```

---

### GET /wings
List wings (now should only show "conversations")

**Example:**
```bash
curl http://localhost:8000/wings
```

**Response:**
```json
{
  "wings": ["conversations"],
  "architecture": "room-based",
  "description": "All conversations stored in single 'conversations' wing, organized by rooms"
}
```

---

## Python Code Examples

### Mining with Python
```python
import requests

# Mine data to a room
response = requests.post(
    'http://localhost:8000/mine',
    files={'file': open('data.jsonl', 'rb')},
    params={'room': 'support_tickets'}
)
print(response.json())
```

### Searching with Python
```python
import requests

# Search all rooms
response = requests.get(
    'http://localhost:8000/search',
    params={'query': 'error', 'n_results': 10}
)
results = response.json()
print(f"Found {results['results_count']} results")
for result in results['results']:
    print(f"  - {result['text'][:100]}")
```

---

## Troubleshooting

### Q: I'm getting an error about missing room parameter
**A:** Room is now **required** for mining. Add `-F "room=your_room_name"` to your curl command.

### Q: My search queries are returning empty
**A:** Check that you have mined data to the room you're searching. Use `/rooms` to see what rooms exist.

### Q: I have data in multiple wings, what do I do?
**A:** You'll need to migrate your data. Each wing should become a separate room under the conversations wing. Data structure stays the same, just organization changes.

### Q: Can I still search specific groups?
**A:** Yes! Use the `room` parameter: `?query=text&room=specific_room`

---

## Migration Checklist

If upgrading from old wing-based system:

- [ ] Update mining scripts to remove `wing` parameter
- [ ] Update mining scripts to add meaningful `room` names
- [ ] Update search scripts to remove `wing` parameter
- [ ] Update search scripts to use `room` for scoping (if needed)
- [ ] Plan data migration if you have existing multi-wing data
- [ ] Test API endpoints with new parameters
- [ ] Update documentation
- [ ] Update client applications
- [ ] Monitor initial searches to verify results

---

## Summary

```
OLD: Multiple wings, each with rooms
POST /mine?wing=healthcare&room=cardiology
GET /search?wing=healthcare

NEW: Single wing (conversations), multiple rooms
POST /mine?room=healthcare_cardiology
GET /search              (searches all rooms)
GET /search?room=healthcare_cardiology  (search specific room)
```

**Everything is simpler! Just provide a room name.** ✨

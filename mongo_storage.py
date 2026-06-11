"""
MongoDB Vector Storage Layer for MemPalace

Replaces Chroma with MongoDB for vector storage while maintaining wing-based isolation.
Supports both MongoDB Atlas and local MongoDB deployment.
"""

import os
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

logger = logging.getLogger("mempalace-mongodb")

# MongoDB Configuration
MONGODB_URI = os.environ.get(
    "MONGODB_URI",
    "mongodb://localhost:27017/?directConnection=true"
)
MONGODB_DB_NAME = os.environ.get("MONGODB_DB", "mempalace")
MONGODB_TIMEOUT = int(os.environ.get("MONGODB_TIMEOUT", "10000"))

# Global MongoDB client
mongo_client: Optional["MongoVectorStorage"] = None


class MongoVectorStorage:
    """MongoDB-based vector storage for MemPalace"""
    
    def __init__(self, uri: str = MONGODB_URI, db_name: str = MONGODB_DB_NAME, timeout: int = MONGODB_TIMEOUT):
        """
        Initialize MongoDB connection
        
        Args:
            uri: MongoDB connection string
            db_name: Database name
            timeout: Connection timeout in milliseconds
        """
        self.uri = uri
        self.db_name = db_name
        self.timeout = timeout
        self.client: Optional[MongoClient] = None
        self.db = None
        self.collections: Dict[str, Any] = {}
    
    def connect(self) -> bool:
        """
        Connect to MongoDB
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.client = MongoClient(
                self.uri,
                serverSelectionTimeoutMS=self.timeout,
                connectTimeoutMS=self.timeout,
            )
            # Verify connection
            self.client.admin.command('ping')
            self.db = self.client[self.db_name]
            logger.info(f"✓ Connected to MongoDB: {self.db_name}")
            self._create_indexes()
            return True
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error(f"MongoDB connection failed: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from MongoDB"""
        if self.client:
            self.client.close()
            logger.info("✓ MongoDB connection closed")
    
    def _create_indexes(self):
        """Create necessary indexes for efficient queries"""
        if self.db is None:
            return
        
        try:
            # Ensure text index on content for full-text search
            self.db.memories.create_index([("content", "text")])
            # Index for wing-based isolation
            self.db.memories.create_index([("wing", 1), ("room", 1)])
            # Index for similarity searches
            self.db.memories.create_index([("wing", 1), ("room", 1), ("timestamp", -1)])
            logger.info("✓ MongoDB indexes created")
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")
    
    def store_memory(
        self,
        wing: str,
        room: str,
        content: str,
        embedding: List[float],
        source: str = "",
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        Store a memory with vector embedding
        
        Args:
            wing: Wing identifier (client isolation)
            room: Room identifier (conversation group)
            content: Text content
            embedding: Vector embedding
            source: Source file/reference
            metadata: Additional metadata
        
        Returns:
            True if successful, False otherwise
        """
        if self.db is None:
            return False
        
        try:
            doc = {
                "wing": wing,
                "room": room,
                "content": content,
                "embedding": embedding,
                "source": source,
                "metadata": metadata or {},
                "timestamp": datetime.now(timezone.utc),
                "length": len(content)
            }
            result = self.db.memories.insert_one(doc)
            logger.debug(f"Stored memory in {wing}:{room} - {result.inserted_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to store memory: {e}")
            return False
    
    def search_wing(
        self,
        query: str,
        wing: str,
        room: Optional[str] = None,
        n_results: int = 5
    ) -> List[Dict]:
        """
        Search within a wing (client-isolated)
        
        Args:
            query: Search query text
            wing: Wing to search in
            room: Optional room filter
            n_results: Number of results to return
        
        Returns:
            List of matching memories
        """
        if self.db is None:
            return []
        
        try:
            filter_query = {"wing": wing}
            if room:
                filter_query["room"] = room
            
            # Text search within wing
            results = list(self.db.memories.find(
                {**filter_query, "$text": {"$search": query}},
                {"score": {"$meta": "textScore"}}
            ).sort([("score", {"$meta": "textScore"})]).limit(n_results))
            
            # Convert ObjectId to string for JSON serialization
            for doc in results:
                doc["_id"] = str(doc["_id"])
                doc.pop("embedding", None)  # Remove embedding vector from response
            
            logger.debug(f"Found {len(results)} results in {wing}:{room or '*'}")
            return results
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    def search_all_rooms(
        self,
        query: str,
        wing: str,
        n_results: int = 5
    ) -> List[Dict]:
        """
        Search across all rooms in a wing
        
        Args:
            query: Search query text
            wing: Wing to search in
            n_results: Number of results per room
        
        Returns:
            Combined results from all rooms
        """
        if self.db is None:
            return []
        
        try:
            # Get all rooms in wing
            rooms = self.db.memories.distinct("room", {"wing": wing})
            all_results = []
            
            for room in rooms:
                room_results = self.search_wing(query, wing, room, n_results)
                for result in room_results:
                    result["room"] = room
                all_results.extend(room_results)
            
            # Deduplicate by content prefix
            seen = set()
            unique = []
            for doc in all_results:
                key = doc.get("content", "")[:200]
                if key not in seen:
                    seen.add(key)
                    unique.append(doc)
            
            return unique[:n_results]
        except Exception as e:
            logger.error(f"Multi-room search failed: {e}")
            return []
    
    def get_rooms(self, wing: str) -> List[str]:
        """Get all rooms in a wing"""
        if self.db is None:
            return []
        
        try:
            rooms = self.db.memories.distinct("room", {"wing": wing})
            return sorted(rooms)
        except Exception as e:
            logger.error(f"Failed to get rooms: {e}")
            return []
    
    def get_wings(self) -> List[str]:
        """Get all wings in the palace"""
        if self.db is None:
            return []
        
        try:
            wings = self.db.memories.distinct("wing")
            return sorted(wings)
        except Exception as e:
            logger.error(f"Failed to get wings: {e}")
            return []
    
    def clear_wing(self, wing: str) -> bool:
        """Clear all memories in a wing"""
        if self.db is None:
            return False
        
        try:
            result = self.db.memories.delete_many({"wing": wing})
            logger.info(f"Cleared {result.deleted_count} memories from wing '{wing}'")
            return True
        except Exception as e:
            logger.error(f"Failed to clear wing: {e}")
            return False
    
    def clear_room(self, wing: str, room: str) -> bool:
        """Clear all memories in a room"""
        if self.db is None:
            return False
        
        try:
            result = self.db.memories.delete_many({"wing": wing, "room": room})
            logger.info(f"Cleared {result.deleted_count} memories from {wing}:{room}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear room: {e}")
            return False
    
    def get_statistics(self, wing: Optional[str] = None) -> Dict:
        """Get storage statistics"""
        if self.db is None:
            return {}
        
        try:
            if wing:
                count = self.db.memories.count_documents({"wing": wing})
                size = sum(
                    len(doc.get("content", "")) 
                    for doc in self.db.memories.find({"wing": wing}, {"content": 1})
                )
                return {
                    "wing": wing,
                    "document_count": count,
                    "total_size_bytes": size
                }
            else:
                count = self.db.memories.count_documents({})
                wings = self.db.memories.distinct("wing")
                return {
                    "total_documents": count,
                    "wings": len(wings),
                    "wing_list": wings
                }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}


# Global instance functions
def get_storage() -> Optional[MongoVectorStorage]:
    """Get global MongoDB storage instance"""
    global mongo_client
    if mongo_client is None:
        mongo_client = MongoVectorStorage()
    return mongo_client


def initialize_storage() -> Optional[MongoVectorStorage]:
    """Initialize MongoDB storage"""
    global mongo_client
    mongo_client = MongoVectorStorage()
    if mongo_client.connect():
        return mongo_client
    return None


def shutdown_storage():
    """Shutdown MongoDB storage"""
    global mongo_client
    if mongo_client:
        mongo_client.disconnect()
        mongo_client = None

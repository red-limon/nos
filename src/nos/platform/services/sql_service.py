"""
SQL Service - Execute raw SQL queries on the database.

Provides a controlled interface for executing SQL statements with:
- Read-only mode by default (SELECT only)
- Optional write mode for authorized operations
- Query result formatting
- Execution time tracking
- Security controls

Usage:
    from nos.platform.services.sql_service import sql_service
    
    # Read-only query (default)
    result = sql_service.execute("SELECT * FROM ai_provider LIMIT 5")
    
    # Write query (explicit)
    result = sql_service.execute("UPDATE ai_provider SET is_active = 1 WHERE provider_id = 'ollama'", allow_write=True)
"""

import logging
import time
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SQLResult:
    """Result of a SQL query execution."""
    success: bool
    query: str
    rows: List[Dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    columns: List[str] = field(default_factory=list)
    affected_rows: int = 0
    execution_time_ms: float = 0.0
    error: Optional[str] = None
    query_type: str = "UNKNOWN"


class SQLService:
    """
    SQL Service for executing raw queries.
    
    Features:
        - Read-only mode by default for safety
        - Query type detection and validation
        - Result formatting with column names
        - Execution time tracking
        - Dangerous query blocking
    """
    
    # Patterns for query type detection
    QUERY_PATTERNS = {
        "SELECT": re.compile(r"^\s*SELECT\s", re.IGNORECASE),
        "INSERT": re.compile(r"^\s*INSERT\s", re.IGNORECASE),
        "UPDATE": re.compile(r"^\s*UPDATE\s", re.IGNORECASE),
        "DELETE": re.compile(r"^\s*DELETE\s", re.IGNORECASE),
        "CREATE": re.compile(r"^\s*CREATE\s", re.IGNORECASE),
        "ALTER": re.compile(r"^\s*ALTER\s", re.IGNORECASE),
        "DROP": re.compile(r"^\s*DROP\s", re.IGNORECASE),
        "TRUNCATE": re.compile(r"^\s*TRUNCATE\s", re.IGNORECASE),
        "PRAGMA": re.compile(r"^\s*PRAGMA\s", re.IGNORECASE),
        "EXPLAIN": re.compile(r"^\s*EXPLAIN\s", re.IGNORECASE),
        "SHOW": re.compile(r"^\s*SHOW\s", re.IGNORECASE),
        "DESCRIBE": re.compile(r"^\s*DESCRIBE\s", re.IGNORECASE),
    }
    
    # Read-only query types
    READ_ONLY_TYPES = {"SELECT", "PRAGMA", "EXPLAIN", "SHOW", "DESCRIBE"}
    
    # Dangerous patterns to block
    DANGEROUS_PATTERNS = [
        re.compile(r";\s*DROP\s", re.IGNORECASE),  # SQL injection
        re.compile(r";\s*DELETE\s", re.IGNORECASE),  # SQL injection
        re.compile(r"--", re.IGNORECASE),  # Comment injection
        re.compile(r"/\*.*\*/", re.IGNORECASE),  # Block comment
    ]
    
    def __init__(self):
        """Initialize SQL service."""
        self._max_rows = 1000  # Default row limit
    
    def detect_query_type(self, query: str) -> str:
        """
        Detect the type of SQL query.
        
        Args:
            query: SQL query string
            
        Returns:
            Query type (SELECT, INSERT, UPDATE, DELETE, etc.)
        """
        query = query.strip()
        for query_type, pattern in self.QUERY_PATTERNS.items():
            if pattern.match(query):
                return query_type
        return "UNKNOWN"
    
    def is_read_only(self, query: str) -> bool:
        """Check if query is read-only."""
        return self.detect_query_type(query) in self.READ_ONLY_TYPES
    
    def validate_query(self, query: str, allow_write: bool = False) -> Tuple[bool, Optional[str]]:
        """
        Validate a SQL query for safety.
        
        Args:
            query: SQL query string
            allow_write: Whether to allow write operations
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not query or not query.strip():
            return False, "Empty query"
        
        # Check for dangerous patterns
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern.search(query):
                return False, "Query contains potentially dangerous patterns"
        
        # Check if write operation is allowed
        query_type = self.detect_query_type(query)
        if query_type not in self.READ_ONLY_TYPES and not allow_write:
            return False, f"Write operation ({query_type}) not allowed. Use allow_write=True to enable."
        
        # Block DROP and TRUNCATE by default (even with allow_write)
        if query_type in {"DROP", "TRUNCATE"}:
            return False, f"Destructive operation ({query_type}) is blocked for safety"
        
        return True, None
    
    def execute(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        allow_write: bool = False,
        max_rows: Optional[int] = None
    ) -> SQLResult:
        """
        Execute a SQL query.
        
        Args:
            query: SQL query string
            params: Optional query parameters (for parameterized queries)
            allow_write: Allow INSERT/UPDATE/DELETE operations
            max_rows: Maximum rows to return (default: 1000)
            
        Returns:
            SQLResult with query results or error
            
        Example:
            result = sql_service.execute("SELECT * FROM ai_provider WHERE is_active = :active", {"active": True})
        """
        query = query.strip()
        query_type = self.detect_query_type(query)
        max_rows = max_rows or self._max_rows
        
        # Validate query
        is_valid, error = self.validate_query(query, allow_write)
        if not is_valid:
            return SQLResult(
                success=False,
                query=query,
                query_type=query_type,
                error=error
            )
        
        # Execute query
        start_time = time.perf_counter()
        
        try:
            from ..extensions import db
            
            result = db.session.execute(db.text(query), params or {})
            
            execution_time = (time.perf_counter() - start_time) * 1000
            
            # Handle different query types
            if query_type in self.READ_ONLY_TYPES:
                # Fetch results for SELECT-like queries
                try:
                    rows_raw = result.fetchmany(max_rows)
                    columns = list(result.keys()) if result.keys() else []
                    rows = [dict(zip(columns, row)) for row in rows_raw]
                    row_count = len(rows)
                    
                    # Check if there are more rows
                    if row_count >= max_rows:
                        logger.warning(f"Query result truncated to {max_rows} rows")
                    
                    return SQLResult(
                        success=True,
                        query=query,
                        query_type=query_type,
                        rows=rows,
                        row_count=row_count,
                        columns=columns,
                        execution_time_ms=round(execution_time, 2)
                    )
                except Exception as e:
                    # Query might not return rows (e.g., PRAGMA)
                    return SQLResult(
                        success=True,
                        query=query,
                        query_type=query_type,
                        rows=[],
                        row_count=0,
                        execution_time_ms=round(execution_time, 2)
                    )
            else:
                # For write operations, commit and return affected rows
                db.session.commit()
                affected = result.rowcount if hasattr(result, 'rowcount') else 0
                
                return SQLResult(
                    success=True,
                    query=query,
                    query_type=query_type,
                    affected_rows=affected,
                    execution_time_ms=round(execution_time, 2)
                )
                
        except Exception as e:
            from ..extensions import db
            db.session.rollback()
            
            execution_time = (time.perf_counter() - start_time) * 1000
            logger.error(f"SQL execution failed: {e}")
            
            return SQLResult(
                success=False,
                query=query,
                query_type=query_type,
                error=str(e),
                execution_time_ms=round(execution_time, 2)
            )
    
    def get_tables(self) -> List[str]:
        """
        Get list of all tables in the database.
        
        Returns:
            List of table names
        """
        try:
            from ..extensions import db
            
            # SQLite specific
            result = self.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            if result.success:
                return [row["name"] for row in result.rows if not row["name"].startswith("sqlite_")]
            return []
        except Exception as e:
            logger.error(f"Failed to get tables: {e}")
            return []
    
    def describe_table(self, table_name: str) -> SQLResult:
        """
        Get table schema/structure.
        
        Args:
            table_name: Name of the table
            
        Returns:
            SQLResult with column information
        """
        # SQLite specific
        query = f"PRAGMA table_info({table_name})"
        return self.execute(query)
    
    def count_rows(self, table_name: str, where_clause: str = "") -> int:
        """
        Count rows in a table.
        
        Args:
            table_name: Name of the table
            where_clause: Optional WHERE clause (without 'WHERE' keyword)
            
        Returns:
            Row count or -1 on error
        """
        query = f"SELECT COUNT(*) as cnt FROM {table_name}"
        if where_clause:
            query += f" WHERE {where_clause}"
        
        result = self.execute(query)
        if result.success and result.rows:
            return result.rows[0].get("cnt", 0)
        return -1


# Global singleton instance
sql_service = SQLService()


__all__ = [
    "SQLService",
    "SQLResult",
    "sql_service",
]

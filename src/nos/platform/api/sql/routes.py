"""
SQL API routes.

Provides endpoints for executing raw SQL queries on the database.
Uses SQLService for controlled query execution.

Endpoints:
- POST /api/sql/execute   Execute a SQL query
- GET /api/sql/tables     List all database tables
- GET /api/sql/describe   Describe a table structure
"""

import logging
from flask import jsonify, request
from typing import Optional

from ..routes import api_bp
from ...services.sql_service import sql_service, SQLResult

logger = logging.getLogger(__name__)


@api_bp.post("/sql/execute")
@api_bp.post("/sql/execute/")
def execute_sql():
    """
    Execute a SQL query.
    
    Request body:
        {
            "query": "SELECT * FROM table",
            "params": {"key": "value"},  // optional
            "allow_write": false,         // optional, default false
            "max_rows": 1000              // optional, default 1000
        }
    
    Returns:
        {
            "success": true,
            "query": "SELECT ...",
            "query_type": "SELECT",
            "rows": [...],              // for SELECT queries
            "columns": [...],           // for SELECT queries
            "row_count": 10,            // for SELECT queries
            "affected_rows": 5,         // for write queries
            "execution_time_ms": 12.5,
            "error": null
        }
    """
    data = request.get_json()
    
    if not data:
        return jsonify({
            "success": False,
            "error": "Request body must be JSON"
        }), 400
    
    query = data.get("query", "").strip()
    if not query:
        return jsonify({
            "success": False,
            "error": "Missing required field: query"
        }), 400
    
    params = data.get("params")
    allow_write = data.get("allow_write", False)
    max_rows = data.get("max_rows")
    
    try:
        result = sql_service.execute(
            query=query,
            params=params,
            allow_write=allow_write,
            max_rows=max_rows
        )
        
        response = {
            "success": result.success,
            "query": result.query,
            "query_type": result.query_type,
            "execution_time_ms": result.execution_time_ms,
            "error": result.error
        }
        
        if result.rows or result.query_type in sql_service.READ_ONLY_TYPES:
            response["rows"] = result.rows
            response["columns"] = result.columns
            response["row_count"] = result.row_count
        
        if result.affected_rows > 0:
            response["affected_rows"] = result.affected_rows
        
        status_code = 200 if result.success else 400
        return jsonify(response), status_code
        
    except Exception as e:
        logger.error(f"SQL API error: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@api_bp.get("/sql/tables")
@api_bp.get("/sql/tables/")
def get_sql_tables():
    """
    Get list of all database tables.
    
    Returns:
        {
            "tables": [
                {"name": "table1", "row_count": 100},
                {"name": "table2", "row_count": 50}
            ]
        }
    """
    try:
        tables = sql_service.get_tables()
        
        result = []
        for table in tables:
            count = sql_service.count_rows(table)
            result.append({
                "name": table,
                "row_count": count
            })
        
        return jsonify({
            "success": True,
            "tables": result,
            "count": len(result)
        })
        
    except Exception as e:
        logger.error(f"Tables API error: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@api_bp.get("/sql/describe/<table_name>")
@api_bp.get("/sql/describe/<table_name>/")
def describe_sql_table(table_name: str):
    """
    Get table structure/schema.
    
    Args:
        table_name: Name of the table to describe
    
    Returns:
        {
            "table": "table_name",
            "columns": [
                {"name": "col1", "type": "INTEGER", "nullable": false, "pk": true, "default": null},
                ...
            ]
        }
    """
    try:
        result = sql_service.describe_table(table_name)
        
        if result.success:
            columns = []
            for row in result.rows:
                columns.append({
                    "name": row.get("name"),
                    "type": row.get("type"),
                    "nullable": not bool(row.get("notnull", 0)),
                    "primary_key": bool(row.get("pk", 0)),
                    "default": row.get("dflt_value")
                })
            
            return jsonify({
                "success": True,
                "table": table_name,
                "columns": columns,
                "column_count": len(columns)
            })
        else:
            return jsonify({
                "success": False,
                "table": table_name,
                "error": result.error or f"Table '{table_name}' not found or has no columns"
            }), 404
            
    except Exception as e:
        logger.error(f"Describe API error: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@api_bp.post("/sql/query")
@api_bp.post("/sql/query/")
def query_sql():
    """
    Alias for /sql/execute with read-only mode forced.
    Convenience endpoint for SELECT queries only.
    
    Request body:
        {
            "query": "SELECT * FROM table",
            "params": {"key": "value"},  // optional
            "max_rows": 1000              // optional
        }
    """
    data = request.get_json()
    
    if not data:
        return jsonify({
            "success": False,
            "error": "Request body must be JSON"
        }), 400
    
    query = data.get("query", "").strip()
    if not query:
        return jsonify({
            "success": False,
            "error": "Missing required field: query"
        }), 400
    
    # Force read-only
    params = data.get("params")
    max_rows = data.get("max_rows")
    
    try:
        result = sql_service.execute(
            query=query,
            params=params,
            allow_write=False,  # Always read-only
            max_rows=max_rows
        )
        
        response = {
            "success": result.success,
            "query_type": result.query_type,
            "rows": result.rows,
            "columns": result.columns,
            "row_count": result.row_count,
            "execution_time_ms": result.execution_time_ms,
            "error": result.error
        }
        
        status_code = 200 if result.success else 400
        return jsonify(response), status_code
        
    except Exception as e:
        logger.error(f"Query API error: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

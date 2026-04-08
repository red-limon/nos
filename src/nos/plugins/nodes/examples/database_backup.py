"""
Database Backup Node Plugin.

Automated backup of production database to cloud storage.
Includes compression and integrity check.

Module path: nos.plugins.nodes.examples.database_backup
Class name:  DatabaseBackupNode
Node ID:     database_backup

To register this node:
    reg node database_backup DatabaseBackupNode nos.plugins.nodes.examples.database_backup

To execute this node:
    run node db database_backup --sync --debug
"""

from nos.core.engine.base import Node, NodeOutput
from datetime import datetime
import random
import time


class DatabaseBackupNode(Node):
    """
    Database Backup - Creates compressed backups with integrity verification.
    
    This node connects to the database, creates a full or incremental backup,
    compresses the data, uploads to cloud storage, and verifies integrity.
    
    Input params:
        backup_type: "full" or "incremental" (default: full)
        compress: Whether to compress backup (default: True)
        cloud_provider: Target cloud storage (default: "s3")
        bucket: S3 bucket name
        verify: Run integrity check after backup (default: True)
    
    Output:
        backup_path: Path to the backup file
        size_mb: Backup size in megabytes
        checksum: MD5 checksum for verification
        duration_seconds: Time taken for backup
    """
    
    def __init__(self, node_id: str = "database_backup", name: str = None):
        super().__init__(node_id, name or "Database Backup")
    
    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        start_time = time.time()
        
        self.exec_log.log("info", "Starting database backup process...")
        
        # Get parameters
        backup_type = params_dict.get("backup_type", "full")
        compress = params_dict.get("compress", True)
        cloud_provider = params_dict.get("cloud_provider", "s3")
        bucket = params_dict.get("bucket", "nos-backups")
        verify = params_dict.get("verify", True)
        
        self.exec_log.log("debug", f"Backup type: {backup_type}")
        self.exec_log.log("debug", f"Cloud provider: {cloud_provider}")
        
        # Simulate database connection
        self.exec_log.log("info", "Connecting to database...")
        time.sleep(0.5)
        self.exec_log.log("info", "Connected to PostgreSQL database")
        
        # Simulate backup creation
        self.exec_log.log("info", f"Creating {backup_type} backup...")
        self.exec_log.log("info", "Backup status: backing_up", status="backing_up")
        
        # Simulate progress
        tables = ["users", "orders", "products", "invoices", "logs"]
        for i, table in enumerate(tables):
            self.exec_log.log("debug", f"Backing up table: {table}...")
            time.sleep(0.3)
            progress = ((i + 1) / len(tables)) * 100
            self.exec_log.log("info", f"Progress: {progress:.0f}%", progress=f"{progress:.0f}%")
        
        # Generate mock backup info
        backup_size = random.randint(500, 2000)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_{backup_type}_{timestamp}.sql"
        
        # Simulate compression
        compressed_size = backup_size
        if compress:
            self.exec_log.log("info", "Compressing backup file...")
            time.sleep(0.5)
            compressed_size = int(backup_size * 0.3)
            backup_filename += ".gz"
            self.exec_log.log("info", f"Compression ratio: {(1 - compressed_size/backup_size)*100:.1f}%")
        
        # Simulate upload
        self.exec_log.log("info", f"Uploading to {cloud_provider}://{bucket}/...")
        time.sleep(0.5)
        backup_path = f"{cloud_provider}://{bucket}/backups/{backup_filename}"
        self.exec_log.log("info", f"Upload complete: {backup_path}")
        
        # Generate checksum
        checksum = f"md5:{random.randint(10000000, 99999999):x}{random.randint(10000000, 99999999):x}"
        
        # Verify integrity
        if verify:
            self.exec_log.log("info", "Verifying backup integrity...")
            time.sleep(0.3)
            self.exec_log.log("info", "Integrity check passed!")
        
        duration = time.time() - start_time
        
        self.exec_log.log("info", f"Database backup completed in {duration:.1f}s")
        
        return NodeOutput(
            output={
                "status": "success",
                "backup_path": backup_path,
                "size_mb": compressed_size,
                "original_size_mb": backup_size,
                "checksum": checksum,
                "duration_seconds": round(duration, 2),
                "tables_backed_up": len(tables),
                "compressed": compress,
                "verified": verify
            },
            metadata={
                "executed_by": "DatabaseBackupNode",
                "backup_type": backup_type,
                "cloud_provider": cloud_provider
            }
        )

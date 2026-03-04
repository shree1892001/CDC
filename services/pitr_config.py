"""
PITR Configuration for CDC Backup System
Centralized configuration for Point-in-Time Recovery
"""

import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).parent.parent
BACKUP_BASE_DIR = BASE_DIR / "cdc_backups"
TRANSACTION_LOG_DIR = BASE_DIR / "transaction_logs"
METADATA_DIR = BASE_DIR / "backup_metadata"

# PITR Configuration
PITR_CONFIG = {
    # Backup settings
    'backup_dir': str(BACKUP_BASE_DIR),
    'transaction_log_dir': str(TRANSACTION_LOG_DIR),
    'metadata_dir': str(METADATA_DIR),
    
    # Retention settings
    'retention_days': 30,  # Keep backups for 30 days
    'max_backup_size_mb': 1000,  # Max size before rotation
    
    # Storage settings
    'compression_enabled': False,  # Disabled for direct restorability via psql
    'compression_level': 6,
    'backup_format': 'sql',  # 'sql' for direct restorability, 'jsonl' for structured
    'base_backup_format': 'custom',  # 'custom' (pg_dump -Fc) for pg_restore compatibility

    
    # Transaction settings
    'batch_size': 20,  # Number of changes to batch before writing (reduced for responsiveness)
    'flush_interval_seconds': 5,  # Force flush every N seconds (checked on next change)
    'background_flush_interval': 5,  # Background check for flushes every N seconds
    
    # Recovery settings
    'enable_transaction_consistency': True,  # Only recover to transaction boundaries
    'verify_lsn_continuity': True,  # Verify LSN sequence is continuous
    
    # Logging
    'log_level': 'INFO',
    'log_file': 'pitr_backup.log',
    'log_max_bytes': 10 * 1024 * 1024,  # 10MB
    'log_backup_count': 5,
}

# Create directories if they don't exist
for dir_path in [BACKUP_BASE_DIR, TRANSACTION_LOG_DIR, METADATA_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# Database connection settings (imported from Common.constants)
DB_CONFIG = {
    'dbname': os.getenv('PG_DB', 'test'),
    'host': os.getenv('PG_HOST', '127.0.0.1'),
    'user': os.getenv('PG_USER', 'postgres'),
    'password': os.getenv('PG_PASSWORD', 'postgres'),
    'port': int(os.getenv('PG_PORT', 5432)),
}

# Replication settings
REPLICATION_CONFIG = {
    'slot_name': 'vstatetest_slot_temp_v2',  # Changed to bypass lock
    'output_plugin': 'test_decoding',  # or 'pgoutput' for native logical replication
    'publication_name': 'cdc_publication',  # if using pgoutput
    'temporary': True  # New flag to indicate temporary slot
}

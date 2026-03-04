# Automatic Incremental Backup Restoration

The project now includes **automatic restoration** of incremental backups through the `AutoRestoreManager` class and `auto_restore.py` daemon.

## Overview

Instead of manually running restore commands, the system can now:

1. **Monitor** the backup directory for new backups as they are created by `main.py`
2. **Detect** new incremental backup files in the metadata catalog
3. **Automatically restore** each backup to a test database in chronological order
4. **Verify** backup integrity and log all operations

This ensures that **every backup is immediately validated by restoration** to a test
database, catching corruption or restore failures early.

## Architecture

### AutoRestoreManager (`services/AutoRestoreManager.py`)

The core class that:
- Runs as a background daemon thread
- Monitors the backup catalog for new backups every N seconds (default: 10s)
- Builds restore chains using `BackupChainBuilder`
- Applies backups in order to a test database using `EnhancedPITRRestoreManager`
- Tracks which backups have been processed
- Logs all operations to `auto_restore.log`

### auto_restore.py

A standalone script that spawns and manages an `AutoRestoreManager` daemon.
Can be run in a separate terminal or as a background process.

## Usage

### Option 1: Run as a standalone daemon

In a separate terminal:

```bash
python auto_restore.py
```

Or specify a custom test database:

```bash
python auto_restore.py --test-db my_test_database
```

Or set the monitor interval:

```bash
python auto_restore.py --interval 5
```

### Option 2: Integrate into main.py

Edit `main.py` to start auto-restore automatically:

```python
from services.AutoRestoreManager import AutoRestoreManager

# In the main() function, after starting replication:
auto_restore_mgr = AutoRestoreManager()
auto_restore_mgr.start()

# Then continue with the normal flow
cdc_processor.consume_changes()
```

### Option 3: Python API

Use directly in your code:

```python
from services.AutoRestoreManager import AutoRestoreManager

manager = AutoRestoreManager(test_db_name='test_restore')
manager.start()

# ... your code ...

# Check status
status = manager.get_status()
print(f"Processed {status['processed_backups']} backups")

# Stop when done
manager.stop()
```

## Workflow

### Typical setup:

```bash
# Terminal 1: Run main CDC processor
python main.py

# Terminal 2: Run auto-restore daemon
python auto_restore.py --test-db mydb_restore_test
```

### What happens:

1. `main.py` creates a base backup and starts capturing CDC changes
2. `main.py` produces incremental `.sql` files as changes occur
3. `auto_restore.py` detects new backups in the metadata catalog every 10 seconds
4. For each new backup, `auto_restore.py`:
   - Builds the full restore chain (base + all incrementals up to that point)
   - Restores the base backup to the test database
   - Applies each incremental in order
   - Logs success/failure
5. If any restore fails, it's logged to `auto_restore.log` and the error is reported

## Configuration

Edit `services/pitr_config.py` to customize:

```python
PITR_CONFIG = {
    'backup_dir': 'cdc_backups',           # Where backups are stored
    'metadata_dir': 'backup_metadata',     # Where catalog and metadata live
    'backup_format': 'sql',                # Backup format (sql, jsonl, etc.)
    'compression_enabled': False,          # Enable gzip compression
    # ... other settings
}

DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'user': 'your_user',
    'password': 'your_password',
    'dbname': 'production_db',
    # ...
}
```

The test database name defaults to `{DB_CONFIG['dbname']}_restore_test` but can be
overridden via `--test-db`.

## Logging

Auto-restore logs are written to `auto_restore.log` in the project root:

```
2026-03-03 19:00:01 - INFO - AutoRestoreManager initialized for test database: mydb_restore_test
2026-03-03 19:00:05 - INFO - Monitor loop started. Checking every 10s
2026-03-03 19:00:15 - INFO - Found 1 new backup(s) to process
2026-03-03 19:00:15 - INFO - Processing backup b_20260303_19_00_10 (type: incremental)
2026-03-03 19:00:15 - INFO - Building restore chain up to 2026-03-03 19:00:10
2026-03-03 19:00:15 - INFO - Chain has 2 backup(s)
2026-03-03 19:00:25 - INFO - Restore successful: 2 backups, 150 changes applied
```

## Status Checking

You can query the auto-restore manager status programmatically:

```python
status = manager.get_status()
print(status)
# Output:
# {
#     'running': True,
#     'test_database': 'mydb_restore_test',
#     'processed_backups': 3,
#     'last_restore_time': '2026-03-03T19:05:30.123456',
#     'processed_backup_ids': ['b_20260303_18_55_10', 'b_20260303_19_00_10', 'b_20260303_19_05_10']
# }
```

## Limitations

- **Base backups**: Currently the auto-restore skips base backups because they require
  schema/DDL setup. Base backups are typically restored manually or as part of an
  initial database setup.
- **Incremental-only**: Only incremental backups are automatically restored. The test
  database must already have a base schema from the most recent base backup restore.
- **Single test database**: Each auto-restore instance targets one test database. If you
  need multiple test databases, run multiple `auto_restore.py` instances with different
  `--test-db` values.

## Troubleshooting

### No backups are being restored

1. Check that `main.py` is running and producing backups:
   ```bash
   ls -l cdc_backups/
   cat backup_metadata/backup_catalog.json
   ```

2. Check the `auto_restore.log` for errors:
   ```bash
   tail -f auto_restore.log
   ```

3. Ensure the test database exists or credentials are correct (PostgreSQL will auto-create it on first restore of a base backup).

### Restore failures

Check `auto_restore.log` for details. Common issues:

- Test database doesn't exist → Let the first base backup create it automatically
- PostgreSQL credentials wrong → Update `services/pitr_config.py`
- Backup files missing → Ensure `backup_dir` path is correct and backups are present

## Next Steps

- Combine with monitoring/alerting to catch restore failures
- Add metrics/prometheus export for backup processing times
- Implement parallel restore of independent backups
- Add web dashboard to monitor restore status

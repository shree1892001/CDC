# CDC Backup with Point-in-Time Recovery (PITR)

## Overview

This system provides production-ready Change Data Capture (CDC) with Point-in-Time Recovery capabilities for PostgreSQL databases. It uses **LSN-tracked CDC** without WAL archiving, making it simpler to operate while still providing transaction-consistent recovery.

## Architecture

### Key Components

1. **CDCProcessorPITR** - Captures changes from PostgreSQL logical replication
2. **PITRBackupManager** - Manages backups with LSN tracking and compression
3. **TransactionLogManager** - Tracks transaction boundaries for consistency
4. **PITRRestoreManager** - Handles point-in-time restoration
5. **Restore CLI** - Command-line tool for restore operations

### How It Works

```
PostgreSQL Logical Replication
         ↓
   CDC Processor
         ↓
    ┌────┴────┐
    ↓         ↓
Transaction  Backup
 Manager    Manager
    ↓         ↓
Transaction  Backup
  Logs       Files
    └────┬────┘
         ↓
   Restore Manager
         ↓
  Point-in-Time Recovery
```

## Features

✅ **LSN Tracking** - Every change tracked with Log Sequence Number  
✅ **Transaction Consistency** - Only restore to committed transaction boundaries  
✅ **Compression** - Automatic gzip compression of backup files  
✅ **Buffering** - Efficient batch writes to minimize I/O  
✅ **Retention Policies** - Automatic cleanup of old backups  
✅ **Backup Catalog** - Searchable index of all backups  
✅ **CLI Tools** - Easy-to-use command-line interface  
✅ **Production-Ready** - No PostgreSQL configuration changes required  

## Setup

### Prerequisites

- PostgreSQL 10+ with logical replication enabled
- Python 3.7+
- Required Python packages: `psycopg2`, `tabulate`

### Installation

1. **Install dependencies:**
   ```bash
   pip install psycopg2-binary tabulate
   ```

2. **Configure PostgreSQL for logical replication:**
   
   Edit `postgresql.conf`:
   ```conf
   wal_level = logical
   max_replication_slots = 10
   max_wal_senders = 10
   ```
   
   Restart PostgreSQL:
   ```bash
   # Windows
   net stop postgresql-x64-14
   net start postgresql-x64-14
   
   # Linux
   sudo systemctl restart postgresql
   ```

3. **Create replication slot:**
   ```bash
   python main_pitr.py --create-slot
   ```

### Configuration

Edit `services/pitr_config.py` to customize:

```python
PITR_CONFIG = {
    'retention_days': 30,           # Keep backups for 30 days
    'max_backup_size_mb': 1000,     # Rotate after 1GB
    'compression_enabled': True,     # Enable gzip compression
    'batch_size': 100,              # Batch size for writes
    'flush_interval_seconds': 5,    # Force flush every 5 seconds
}
```

## Usage

### Starting CDC Capture

**Basic usage:**
```bash
python main_pitr.py
```

**With custom settings:**
```bash
python main_pitr.py --slot-name my_slot --plugin pgoutput --backup-dir D:\backups
```

**Show statistics:**
```bash
python main_pitr.py --stats
```

### Restore Operations

#### List Available Backups

```bash
python restore_cli.py list-backups
```

#### Create a Base Snapshot

Before starting captures, generate a full snapshot to restore onto:

```bash
python restore_cli.py base-backup --db test
```

**With custom output:**
```bash
python restore_cli.py base-backup --db test --output my_snapshot.sql
```

#### List Recovery Points

```bash
python restore_cli.py list-recovery-points
```

#### Preview a Restore

Before performing a restore, preview what will happen:

```bash
python restore_cli.py preview --timestamp "2024-01-15 14:30:00"
```

Output:
```
✅ Valid recovery point found (12.5s before target)

Target timestamp:        2024-01-15 14:30:00
Actual restore time:     2024-01-15 14:29:47
Recovery point LSN:      0/12345678
Recovery point TxID:     12345

Backups to process:      3
Total changes to apply:  1,234
Tables affected:         users, orders, products
```

#### Perform a Restore

**Dry run (recommended first):**
```bash
python restore_cli.py restore --timestamp "2024-01-15 14:30:00" --target-db test_restore --dry-run
```

**Actual restore:**
```bash
python restore_cli.py restore --timestamp "2024-01-15 14:30:00" --target-db test_restore --yes
```

**Restore specific tables only:**
```bash
python restore_cli.py restore --timestamp "2024-01-15 14:30:00" --target-db test_restore --tables users orders --yes
```

**Restore to specific LSN:**
```bash
python restore_cli.py restore-lsn --lsn "0/12345678" --target-db test_restore --yes
```

#### Show Statistics

```bash
python restore_cli.py stats
```

## File Structure

```
CDC/
├── main_pitr.py                    # Main entry point for CDC
├── restore_cli.py                  # CLI tool for restore operations
├── services/
│   ├── pitr_config.py             # Configuration
│   ├── CDCProcessorPITR.py        # Enhanced CDC processor
│   ├── PITRBackupManager.py       # Backup management
│   ├── TransactionLogManager.py   # Transaction tracking
│   └── PITRRestoreManager.py      # Restore operations
├── cdc_backups/                   # Backup files
│   ├── cdc_backup_20240115_143000.jsonl.gz
│   └── ...
├── backup_metadata/               # Backup metadata
│   ├── backup_catalog.json
│   ├── backup_points.json
│   └── ...
└── transaction_logs/              # Transaction logs
    ├── transactions_20240115.jsonl
    └── ...
```

## Backup File Format

Backups are stored as **executable SQL statements** with metadata metadata in comments for PITR:

```sql
-- LSN: 0/1A2B3C4D, TXID: 1001, TS: 2024-01-15T14:30:00
INSERT INTO public.users (id, name, email) VALUES (1, 'Alice', 'alice@example.com');

-- LSN: 0/1A2B3C4E, TXID: 1001, TS: 2024-01-15T14:30:05
UPDATE public.users SET name = 'Alice Smith' WHERE id = 1;
```

Each record contains:
- **LSN**: Log Sequence Number (metadata comment)
- **TXID**: Transaction ID (metadata comment)
- **TS**: Change timestamp (metadata comment)
- **SQL**: The actual DML statement (INSERT, UPDATE, or DELETE)

## Transaction Consistency

The system ensures transaction consistency by:

1. **Tracking BEGIN/COMMIT/ROLLBACK** - All transaction boundaries are recorded
2. **Grouping changes by transaction** - Changes are associated with their transaction
3. **Only restoring committed transactions** - Rolled back transactions are excluded
4. **Finding nearest commit point** - Restores to the last committed transaction before target time

Example:
```
Target time: 14:30:00

Transaction 1: BEGIN 14:29:45 → COMMIT 14:29:50 ✅ Included
Transaction 2: BEGIN 14:29:55 → COMMIT 14:30:05 ❌ Excluded (commits after target)
Transaction 3: BEGIN 14:29:58 → (active)        ❌ Excluded (not committed)

Restore point: 14:29:50 (Transaction 1 commit)
```

## Best Practices

### For Production Use

1. **Monitor disk space** - Backups can grow large, monitor `cdc_backups/` directory
2. **Set appropriate retention** - Balance recovery needs with storage costs
3. **Test restores regularly** - Verify backups are working correctly
4. **Use separate restore database** - Never restore directly to production
5. **Monitor CDC lag** - Ensure CDC processor keeps up with changes

### Performance Optimization

1. **Adjust batch size** - Larger batches = fewer writes but more memory
2. **Enable compression** - Saves disk space at cost of CPU
3. **Use JSONL format** - More efficient than JSON for large files
4. **Tune flush interval** - Balance between data loss risk and I/O

### Disaster Recovery

1. **Backup the backup directory** - Copy `cdc_backups/` and `backup_metadata/` to remote storage
2. **Document recovery procedures** - Keep runbooks for restore operations
3. **Test recovery scenarios** - Practice restoring to different points in time
4. **Monitor replication slot** - Ensure slot doesn't fall too far behind

## Troubleshooting

### CDC Processor Not Capturing Changes

**Check replication slot:**
```sql
SELECT * FROM pg_replication_slots WHERE slot_name = 'vstatetest_slot';
```

**Check if slot is active:**
```sql
SELECT * FROM pg_stat_replication;
```

**Recreate slot if needed:**
```bash
python main_pitr.py --create-slot
```

### Restore Fails with "input file does not appear to be a valid archive"

This error happens when you try to use `pg_restore` on a plain SQL file (like our incremental backups).

**Solution:**
1. Use the `check-file` command to see which tool to use:
   ```bash
   python restore_cli.py check-file D:\CDC\cdc_backup_20260205_062738.sql
   ```
2. Use `psql` for `.sql` files:
   ```bash
   psql -h 127.0.0.1 -d test -f D:\CDC\cdc_backup_20260205_062738.sql
   ```
3. Only use `pg_restore` for base snapshots ending in `.dump` (custom format).

### Restore Fails with "No recovery points found"

This means no committed transactions exist before the target time.

**Check available recovery points:**
```bash
python restore_cli.py list-recovery-points
```

**Verify backups exist:**
```bash
python restore_cli.py list-backups
```

### High Disk Usage

**Check backup statistics:**
```bash
python restore_cli.py stats
```

**Clean up old backups manually:**
```python
from services.PITRBackupManager import PITRBackupManager
manager = PITRBackupManager()
manager.cleanup_old_backups(retention_days=7)
```

**Enable compression if not already:**
```python
# In pitr_config.py
PITR_CONFIG['compression_enabled'] = True
```

### CDC Processor Crashes

**Check logs:**
```bash
cat cdc_changes.log
cat pitr_backup.log
```

**Verify database connection:**
```bash
psql -h 127.0.0.1 -U postgres -d test
```

**Check last processed LSN:**
```bash
cat last_lsn.txt
```

## Advanced Usage

### Creating Named Backup Points

Create a labeled backup point for easy recovery:

```python
from services.PITRBackupManager import PITRBackupManager

manager = PITRBackupManager()
manager.create_backup_point(
    label="before_migration",
    description="Backup before schema migration"
)
```

### Programmatic Restore

```python
from services.PITRRestoreManager import PITRRestoreManager
from datetime import datetime

restore_manager = PITRRestoreManager()

# Preview restore
preview = restore_manager.preview_restore(
    datetime(2024, 1, 15, 14, 30, 0)
)
print(preview)

# Perform restore
result = restore_manager.restore_to_timestamp(
    target_timestamp=datetime(2024, 1, 15, 14, 30, 0),
    target_db='test_restore',
    tables=['users', 'orders'],
    dry_run=False
)
print(result)
```

### Custom Retention Policies

```python
from services.PITRBackupManager import PITRBackupManager
from services.TransactionLogManager import TransactionLogManager

backup_manager = PITRBackupManager()
tx_manager = TransactionLogManager()

# Clean up backups older than 7 days
backup_manager.cleanup_old_backups(retention_days=7)

# Clean up transaction logs older than 14 days
tx_manager.cleanup_old_logs(retention_days=14)
```

## Comparison with WAL Archiving

| Feature | LSN-Tracked CDC (No-WAL) | WAL Archiving |
|---------|-----------------|---------------|
| **Setup** | Simple (no WAL config) | Complex (requires archive_mode) |
| **Storage** | Efficient (SQL changes only) | High (all database activity) |
| **Recovery** | Incremental SQL Replay | Physical WAL Replay |
| **Operations** | Direct `psql` restorability | `pg_restore` / Physical recovery |
| **Granularity** | Transaction boundaries | Exact LSN/timestamp |
| **Scope** | CDC-tracked tables | Entire database |

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review logs in `cdc_changes.log` and `pitr_backup.log`
3. Verify configuration in `services/pitr_config.py`

## License

This is part of your CDC project.

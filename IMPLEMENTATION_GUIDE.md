# Implementation Guide - Incremental Backup Restoration

## Overview

This guide shows how to integrate the enhanced backup manager and restore manager into your existing CDC system to support true incremental backup restoration.

## Files Created

1. **`services/EnhancedBackupManager.py`** - Backup lineage and chain building
2. **`services/EnhancedRestoreManager.py`** - Enhanced restore with chain support

## Quick Start Integration

### Step 1: Update PITRBackupManager to Use Lineage

Edit `services/PITRBackupManager.py` to add lineage tracking:

```python
# At the top of the file, add:
from .EnhancedBackupManager import EnhancedBackupMetadata

# In PITRBackupManager.__init__, change:
self.current_backup_metadata = {
    'backup_id': timestamp,
    # ... existing fields ...
}

# To use EnhancedBackupMetadata:
meta = EnhancedBackupMetadata()
meta.backup_id = timestamp
meta.filename = filename
meta.backup_type = 'incremental'  # Set to 'base' for base backups
meta.start_time = datetime.now().isoformat()
# ... set other fields ...

self.current_backup_metadata = meta.to_dict()
```

### Step 2: Mark Base Backups

When creating a base backup, mark it properly:

```python
def create_base_backup(self, target_db: str) -> dict:
    """Create a base backup"""
    # ... existing code to create backup ...
    
    # Mark as base
    self.current_backup_metadata['backup_type'] = 'base'
    self.current_backup_metadata['chain_depth'] = 0
    self.current_backup_metadata['base_backup_id'] = self.current_backup_metadata['backup_id']
    self.current_backup_metadata['parent_backup_id'] = None
    
    return result
```

### Step 3: Link Incremental Backups

In the normal incremental backup creation:

```python
def _initialize_backup_file(self):
    """Initialize a new backup file"""
    # ... existing code ...
    
    # For incremental backups, link to parent
    latest_backup = self._find_latest_backup()
    
    if latest_backup:
        self.current_backup_metadata['parent_backup_id'] = latest_backup['backup_id']
        self.current_backup_metadata['base_backup_id'] = latest_backup.get('base_backup_id', latest_backup['backup_id'])
        self.current_backup_metadata['chain_depth'] = latest_backup.get('chain_depth', 0) + 1
    else:
        # No parent, this is a base
        self.current_backup_metadata['backup_type'] = 'base'
        self.current_backup_metadata['base_backup_id'] = self.current_backup_metadata['backup_id']
```

### Step 4: Update Backup Catalog

Ensure catalog includes lineage info:

```python
# In _save_backup_catalog():
catalog_entry = {
    'backup_id': self.current_backup_metadata['backup_id'],
    'filename': self.current_backup_metadata['filename'],
    'backup_type': self.current_backup_metadata.get('backup_type', 'incremental'),
    'parent_backup_id': self.current_backup_metadata.get('parent_backup_id'),
    'base_backup_id': self.current_backup_metadata.get('base_backup_id'),
    'chain_depth': self.current_backup_metadata.get('chain_depth', 0),
    # ... existing fields ...
}
```

### Step 5: Update Restore CLI

Add new commands to `restore_cli.py`:

```python
def cmd_restore_with_chain(args):
    """Restore using backup chain"""
    from services.EnhancedRestoreManager import EnhancedPITRRestoreManager
    from services.PITRBackupManager import PITRBackupManager
    
    backup_manager = PITRBackupManager()
    restore_manager = EnhancedPITRRestoreManager(backup_manager)
    
    target_time = datetime.fromisoformat(args.timestamp)
    
    result = restore_manager.restore_to_timestamp_with_chain(
        target_timestamp=target_time,
        target_db=args.db or DB_CONFIG['dbname'],
        tables=args.tables.split(',') if args.tables else None,
        verify_before_restore=not args.skip_verify,
        dry_run=args.dry_run,
        show_progress=True
    )
    
    return 0 if result['success'] else 1

# In main argument parser:
restore_parser = subparsers.add_parser('restore-chain', help='Restore using backup chain')
restore_parser.add_argument('timestamp', help='Target timestamp (ISO format)')
restore_parser.add_argument('--db', help='Target database')
restore_parser.add_argument('--tables', help='Comma-separated list of tables to restore')
restore_parser.add_argument('--skip-verify', action='store_true', help='Skip verification')
restore_parser.add_argument('--dry-run', action='store_true', help='Preview only')
restore_parser.set_defaults(func=cmd_restore_with_chain)
```

## Example Usage

### List Backup Chain

```bash
python restore_cli.py list-backups
```

Example output:
```
Backup ID           Filename                           Type        Parent ID       Changes
─────────────────────────────────────────────────────────────────────────────────
20260215_000000    base_snapshot_20260215_000000.sql   BASE        -               -
20260215_120000    cdc_backup_20260215_120000.sql      INCR        20260215_000000 150
20260215_160000    cdc_backup_20260215_160000.sql      INCR        20260215_120000 200
20260215_200000    cdc_backup_20260215_200000.sql      INCR        20260215_160000 180
```

### Preview Restore

```bash
python restore_cli.py restore-chain "2026-02-15 23:30:00" --db test_restore --dry-run
```

Output:
```
======================================================================
Enhanced PITR Restore - Chain Mode
======================================================================
Target timestamp: 2026-02-15 23:30:00
Target database:  test_restore

[1/5] Building restore chain...
      ✓ Built chain with 4 backups
        1. [BASE] base_snapshot_20260215_000000.sql
           Size: 500.0 MB, Changes: 0
        2. [INCR] cdc_backup_20260215_120000.sql
           Size: 45.2 MB, Changes: 150
        3. [INCR] cdc_backup_20260215_160000.sql
           Size: 48.7 MB, Changes: 200
        4. [INCR] cdc_backup_20260215_200000.sql
           Size: 42.1 MB, Changes: 180

[2/5] Verifying backup integrity...
      ✓ All backups verified successfully

[3/5] Analyzing restore impact...
      Total changes to apply: 530
      Tables affected: customers, orders, items, inventory
      Changes (filtered): 530

[4/5] Dry run mode - not making changes
      Would restore 4 backups to test_restore

[5/5] Dry run complete - no changes applied
```

### Execute Restore

```bash
python restore_cli.py restore-chain "2026-02-15 23:30:00" --db test_restore
```

Output:
```
======================================================================
Enhanced PITR Restore - Chain Mode
======================================================================
Target timestamp: 2026-02-15 23:30:00
Target database:  test_restore

[1/5] Building restore chain...
      ✓ Built chain with 4 backups
        1. [BASE] base_snapshot_20260215_000000.sql
           Size: 500.0 MB, Changes: 0
        2. [INCR] cdc_backup_20260215_120000.sql
           Size: 45.2 MB, Changes: 150
        3. [INCR] cdc_backup_20260215_160000.sql
           Size: 48.7 MB, Changes: 200
        4. [INCR] cdc_backup_20260215_200000.sql
           Size: 42.1 MB, Changes: 180

[2/5] Verifying backup integrity...
      ✓ All backups verified successfully

[3/5] Analyzing restore impact...
      Total changes to apply: 530
      Tables affected: customers, orders, items, inventory

[4/5] Restoring backup chain...
      Restoring backup 1/4: base_snapshot_20260215_000000.sql
        ✓ Backup 1/4 applied
      Restoring backup 2/4: cdc_backup_20260215_120000.sql
        ✓ Backup 2/4 applied (150 changes)
      Restoring backup 3/4: cdc_backup_20260215_160000.sql
        ✓ Backup 3/4 applied (200 changes)
      Restoring backup 4/4: cdc_backup_20260215_200000.sql
        ✓ Backup 4/4 applied (180 changes)

[5/5] Verifying restore...
      ✓ Restore completed successfully

======================================================================
✓ Restore completed successfully!
  Backups: 4
  Changes: 530
  Tables:  customers, orders, items, inventory
======================================================================
```

### Verify Backup Integrity

```bash
python restore_cli.py verify-backup 20260215_200000
```

Output:
```
Verifying backup: 20260215_200000
────────────────────────────────────────────────────────────────

File:              cdc_backup_20260215_200000.sql.gz
Size:              42.1 MB
Type:              INCREMENTAL
Parent:            20260215_160000
Changes:           180
Tables:            customers, orders

Verification Results:
  ✓ File exists
  ✓ File not corrupted (size > 0)
  ✓ SHA256 checksum valid: abc123def456...
  ✓ Can parse (sample: 50 records)
  ✓ LSN ordering valid: 0/12345678 → 0/123456AB

Status: VERIFIED
Verified at: 2026-02-15 23:45:00
```

### Show Chain Info

```bash
python restore_cli.py show-chain 20260215_200000
```

Output:
```
Backup Chain for: 20260215_200000

BASE BACKUP
├─ ID:          20260215_000000
├─ File:        base_snapshot_20260215_000000.sql
├─ Size:        500.0 MB
└─ Created:     2026-02-15 00:00:00

INCREMENTAL CHAIN
├─ [1] 20260215_120000
│  ├─ File:    cdc_backup_20260215_120000.sql
│  ├─ Changes: 150
│  ├─ Size:    45.2 MB
│  └─ Created: 2026-02-15 12:00:00
│
├─ [2] 20260215_160000
│  ├─ File:    cdc_backup_20260215_160000.sql
│  ├─ Changes: 200
│  ├─ Size:    48.7 MB
│  └─ Created: 2026-02-15 16:00:00
│
└─ [3] 20260215_200000 ← YOU ARE HERE
   ├─ File:    cdc_backup_20260215_200000.sql
   ├─ Changes: 180
   ├─ Size:    42.1 MB
   └─ Created: 2026-02-15 20:00:00

Chain Statistics:
  Depth:      3 (base + 3 incrementals)
  Total size: 635.0 MB
  Total age:  20 hours
  Can restore to any point from 2026-02-15 00:00:00 to 2026-02-15 20:00:00
```

## Testing the Implementation

### Test 1: Verify Chain Building

```python
# In test script
from services.PITRBackupManager import PITRBackupManager
from services.EnhancedBackupManager import BackupChainBuilder

backup_manager = PITRBackupManager()
chain_builder = BackupChainBuilder(backup_manager.backup_catalog)

# Build chain to specific time
target_time = datetime.now()
chain = chain_builder.build_chain_to_point(target_time)

print(f"Built chain with {len(chain)} backups")
for backup in chain:
    print(f"  - {backup['backup_id']}: {backup['filename']}")
```

### Test 2: Verify Integrity

```python
# In test script
from services.EnhancedBackupManager import BackupIntegrityValidator

validator = BackupIntegrityValidator(backup_manager)

# Verify a specific backup
is_valid, errors = validator.verify_backup_file('20260215_200000', metadata)

if is_valid:
    print("✓ Backup is valid and restorable")
else:
    print("✗ Backup has issues:")
    for error in errors:
        print(f"  - {error}")
```

### Test 3: Test Restore Chain

```python
# In test script
from services.EnhancedRestoreManager import EnhancedPITRRestoreManager

restore_manager = EnhancedPITRRestoreManager(backup_manager)

# Test dry-run restore
target_time = datetime.fromisoformat("2026-02-15 18:30:00")
result = restore_manager.restore_to_timestamp_with_chain(
    target_timestamp=target_time,
    target_db="test_restore",
    dry_run=True,
    show_progress=True
)

print(f"Dry run result: {result}")
```

## Migration Path

### Existing Deployments

If you have an existing CDC system, follow this path:

1. **Backup your backup catalog** before any changes
2. **Add lineage info** to existing backups in catalog:
   ```python
   # Script to migrate existing catalog
   for backup in catalog:
       if backup['backup_type'] == 'base':
           backup['chain_depth'] = 0
           backup['base_backup_id'] = backup['backup_id']
           backup['parent_backup_id'] = None
       else:
           # Find parent (most recent before this)
           # ... logic ...
   ```
3. **Deploy new code** with enhanced managers
4. **Test on staging** first
5. **Monitor production** for issues
6. **Gradually migrate** to new restore procedures

## Troubleshooting

### Chain Building Fails

**Problem:** "Could not build restore chain"

**Solution:**
1. Check backup catalog: `python restore_cli.py list-backups`
2. Verify lineage: `python restore_cli.py show-chain <backup_id>`
3. Look for missing backups in chain
4. Verify backup file exists on disk

### Backup Verification Fails

**Problem:** "Backup verification failed"

**Solution:**
1. Check file exists: `ls -lh backup_metadata/<file>`
2. Check file size > 0
3. Verify checksums: `sha256sum <file>`
4. Check backup is readable (permissions)
5. Try manual restore to test: `psql -f <file>`

### Restore Chain Incomplete

**Problem:** Restore chain has gap

**Solution:**
1. Check for deleted backups: `ls cdc_backups/`
2. Look in backup catalog for deleted entries
3. If base backup missing, start new chain
4. Consider using older base + all incrementals

## Performance Optimization

### Parallel Restore

For large chains, enable parallel change application:

```python
result = restore_manager.restore_to_timestamp_with_chain(
    target_timestamp=target_time,
    target_db="test_restore",
    parallel_workers=4,  # NEW: use 4 worker threads
    show_progress=True
)
```

### Incremental-Only Restore

Skip base backup for recent points:

```python
# If target is < 1 day old, can restore from incrementals only
result = restore_manager.restore_to_timestamp_with_chain(
    target_timestamp=target_time,
    target_db="test_restore",
    incremental_only=True,  # NEW: skip base if possible
    show_progress=True
)
```

## Next Steps

After implementing these improvements, consider:

1. **Multi-level backups** - Differential backups for better compression
2. **Backup encryption** - Encrypt backups at rest
3. **Remote backup** - Ship backups to S3/cloud storage
4. **Automated testing** - Periodic test restores
5. **Metrics/monitoring** - Track backup sizes and restore times

## Support & Questions

For issues or questions:
1. Check logs: `cat pitr_restore_enhanced.log`
2. Enable debug: `PITR_CONFIG['log_level'] = 'DEBUG'`
3. Test with small backups first
4. Verify manually with psql before using CLI

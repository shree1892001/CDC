# CDC Incremental Backup System - Analysis & Improvements

## Current System Overview

### How Incremental Backups Currently Work

The CDC system uses a **two-tier backup approach**:

```
┌─────────────────────────────────────────────────────────┐
│         PostgreSQL Logical Replication Stream            │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
    ┌────────────────────────────┐
    │   CDCProcessorPITR         │
    │  - Captures changes        │
    │  - Tracks LSN & TXID       │
    └────────────┬───────────────┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
    ┌──────────────┐  ┌─────────────────────┐
    │ Base Backup  │  │ Incremental Changes │
    │ (Full dump)  │  │ (LSN-tracked CDC)   │
    │ Created:     │  │ Format: SQL/JSON    │
    │ - Initially  │  │ Storage:            │
    │ - Every 24h  │  │  - cdc_backup_*.sql │
    │ - On demand  │  │  - *.json           │
    └──────────────┘  └─────────────────────┘
        │                     │
        └─────────────┬───────┘
                      ▼
           ┌──────────────────────┐
           │  Backup Manager      │
           │ - Metadata tracking  │
           │ - Compression (gzip) │
           │ - Catalog index      │
           └──────────────────────┘
                      │
                      ▼
           ┌──────────────────────┐
           │  Transaction Manager │
           │ - TXID boundaries    │
           │ - Commit tracking    │
           └──────────────────────┘
```

### Key Components

#### 1. **CDCProcessorPITR** (`services/CDCProcessorPITR.py`)
- Connects via logical replication slot
- Consumes changes from PostgreSQL replication stream
- Tracks LSN (Log Sequence Number) for every change
- Tracks TXID (Transaction ID) for consistency
- Buffers changes and sends to backup manager

#### 2. **PITRBackupManager** (`services/PITRBackupManager.py`)
- **Buffering**: Groups changes in memory before writing (batch size: 100 by default)
- **Flushing**: Writes changes to disk every 5 seconds or when buffer full
- **File Rotation**: Creates new backup files when:
  - File size exceeds `max_backup_size_mb` (1000 MB)
  - New calendar day starts
- **Formats Supported**:
  - `.sql` - SQL statements (executable via `psql`)
  - `.jsonl` - JSON Lines (one JSON object per line)
  - `.json` - JSON array (less efficient, not recommended)
- **Compression**: Optional gzip compression
- **Metadata**: Tracks per-backup:
  - Start/End LSN
  - Start/End timestamp
  - Change count
  - Tables affected
  - Transaction IDs
  - Saved to `backup_metadata/<timestamp>_metadata.json`

#### 3. **TransactionLogManager** (`services/TransactionLogManager.py`)
- Records transaction lifecycle (BEGIN, COMMIT, ROLLBACK)
- Tracks committed vs. active transactions
- Provides consistent recovery points (only at committed transaction boundaries)
- Maintains `transaction_logs/transactions_*.jsonl`

#### 4. **PITRRestoreManager** (`services/PITRRestoreManager.py`)
- Validates restore points (transaction consistency)
- Previews restore operations
- Restores base backups via `pg_restore` or `psql`
- Applies incremental changes in LSN order
- Filters by timestamp, LSN, or specific tables

### Backup Catalog

Located at `backup_metadata/backup_catalog.json`:

```json
[
  {
    "backup_id": "20260215_231239",
    "filename": "cdc_backup_20260215_231239.sql.gz",
    "start_time": "2026-02-15T23:12:39.123456",
    "end_time": "2026-02-15T23:45:00.654321",
    "start_lsn": "0/1234567890",
    "end_lsn": "0/1234567ABC",
    "changes_count": 250,
    "tables_affected": ["users", "orders", "items"],
    "transactions": [12345, 12346, 12347],
    "format": "sql",
    "compressed": true
  }
]
```

---

## Current Restoration Process

### Step-by-Step Restore

```
Target Recovery Point (e.g., 2026-02-15 23:30:00)
            │
            ▼
┌─────────────────────────────────┐
│ 1. Validate Recovery Point       │
│    - Find last committed TX      │
│    - Before target timestamp     │
│    - Verify transaction log      │
└─────────┬───────────────────────┘
          │
          ▼
┌─────────────────────────────────┐
│ 2. Find Base Backup              │
│    - Search backup catalog       │
│    - Find latest before target   │
│    - Verify file exists          │
└─────────┬───────────────────────┘
          │
          ▼
┌─────────────────────────────────┐
│ 3. Restore Base Backup           │
│    - SQL format: psql -f         │
│    - Custom: pg_restore          │
│    - Restores full DB state      │
└─────────┬───────────────────────┘
          │
          ▼
┌─────────────────────────────────┐
│ 4. Collect Incremental Changes   │
│    - Read all backup files       │
│    - After base backup LSN       │
│    - Before recovery point time  │
│    - Filter by table (if needed) │
│    - Sort by LSN                 │
└─────────┬───────────────────────┘
          │
          ▼
┌─────────────────────────────────┐
│ 5. Apply Changes                 │
│    - Generate SQL for each       │
│    - Execute within transaction  │
│    - Verify committed only       │
└─────────┬───────────────────────┘
          │
          ▼
         Restored DB State
```

---

## Current Issues & Limitations

### 🔴 Critical Issues

1. **No Incremental Restore Without Base Backup**
   - System requires a full base backup to restore
   - Incremental-only restore NOT supported
   - Recovery impossible if base backup is missing/corrupted

2. **Incremental Backup Files Are Consumable, Not Reusable**
   - Format: Multiple SQL transactions
   - Each backup file contains FULL changes (not delta)
   - Cannot easily re-apply if restore fails halfway

3. **No Backup Chaining/Lineage**
   - No parent-child relationship tracking
   - Cannot determine which incremental backups depend on which base
   - Difficult to prune old backups safely

4. **Limited Incremental Integrity Checks**
   - No checksums or cryptographic validation
   - No recovery point verification before restore
   - Silent failures possible if data corruption occurs

5. **Metadata Not Embedded in Backup Files**
   - LSN/TXID info only in comments in SQL format
   - Separate JSON metadata files can become out-of-sync
   - If metadata lost, backup useless

### 🟡 Medium Issues

1. **Slow Incremental Restore Performance**
   - Must parse all SQL statements sequentially
   - No parallelization of change application
   - Large backups with many changes take long time

2. **No Differential/Incremental Backup Chains**
   - All incremental backups are "level 0" (not level 1/2)
   - Cannot build multi-level backup chains for faster restores
   - No optimization for unchanged data

3. **Transaction Consistency Only at Commit Boundaries**
   - Cannot restore to exact LSN (must round to last committed TX)
   - May lose recent data if exact point desired

4. **Limited Backup Retention Policies**
   - Basic TTL only (30 days by default)
   - No smart retention (keep fewer old backups, more recent ones)
   - No size-based cleanup

### 🟢 Minor Issues

1. **Compression overhead for small changes**
   - gzip compression added but not verified effective for CDC changes
2. **No progress tracking during long restores**
3. **Limited error recovery during restore failure**

---

## Proposed Improvements

### ✅ Tier 1: Make Incremental Backups Directly Restorable

#### Objective
Enable restore from incremental backups alone (without base backup), or chain multiple incrementals.

#### Implementation

**1. Add Backup Lineage Tracking**

```python
# In PITRBackupManager.py
class BackupMetadata:
    def __init__(self):
        self.backup_id: str          # Unique ID
        self.filename: str           # File name
        self.backup_type: str        # "base" or "incremental"
        
        # NEW FIELDS:
        self.parent_backup_id: Optional[str]  # Parent base/incremental
        self.base_backup_id: str     # Root base backup
        self.chain_depth: int        # 0 = base, 1+ = incremental
        self.sequence_number: int    # Order in chain
        self.full_coverage: bool     # Can restore independently?
        
        # Existing fields
        self.start_lsn: str
        self.end_lsn: str
        self.changes_count: int
        # ... etc
```

**2. Embedded Metadata in Backup Files**

For SQL format:
```sql
-- ========== BACKUP METADATA (DO NOT EDIT) ==========
-- BACKUP_ID: 20260215_231239
-- BACKUP_TYPE: incremental
-- PARENT_BACKUP_ID: 20260215_120000
-- BASE_BACKUP_ID: 20260215_000000
-- CHAIN_DEPTH: 2
-- START_LSN: 0/1234567890
-- END_LSN: 0/1234567ABC
-- CHANGES_COUNT: 250
-- TABLES_AFFECTED: ["users", "orders", "items"]
-- START_TIME: 2026-02-15T23:12:39.123456
-- END_TIME: 2026-02-15T23:45:00.654321
-- CHECKSUM_SHA256: abc123def456...
-- ====================================================

BEGIN;
...
COMMIT;
```

For JSONL format - add metadata record:
```json
{"__metadata__": {"backup_id": "20260215_231239", "parent_id": "20260215_120000", ...}}
{...change 1...}
{...change 2...}
```

**3. Incremental Restore Chain Building**

```python
def restore_to_timestamp(target_timestamp: datetime, target_db: str):
    """
    Restored to a point in time using backup chain
    Automatically chains multiple incremental backups if needed
    """
    # Find recovery point
    recovery_point = self.find_recovery_point(target_timestamp)
    
    # Build chain: base -> incr1 -> incr2 -> ... -> target
    chain = self.backup_manager.build_restore_chain(recovery_point)
    
    print(f"Restore chain ({len(chain)} backups):")
    for i, backup in enumerate(chain):
        print(f"  {i+1}. {backup['filename']} "
              f"({backup['changes_count']} changes)")
    
    # Restore each backup in sequence
    for backup in chain:
        self._restore_backup(backup, target_db)
    
    return {"success": True, "backups_restored": len(chain)}
```

#### Example Backup Chain
```
Base Backup (Feb 15, 00:00)
├─ Incr #1 (00:00 -> 08:00, 100 changes)
├─ Incr #2 (08:00 -> 16:00, 150 changes)
└─ Incr #3 (16:00 -> 23:45, 250 changes)  ← Target point

Restore Feb 15 @ 23:30:
→ Apply Base + Incr#1 + Incr#2 + Incr#3 (filtered to 23:30)
```

---

### ✅ Tier 2: Implement Multi-Level Backup Chains

#### Objective
Support differential/level-based incremental backups for faster recovery.

#### Implementation

**Backup Types:**
- Level 0 (Base): Full database dump
- Level 1 (Incremental): All changes since Level 0
- Level 2 (Differential): Only changes since last Level 1

**Strategy:**
```python
INCREMENTAL_LEVELS = {
    0: "base",           # Full snapshot
    1: "incremental",    # All changes since base
    2: "differential",   # Only changes since last incremental
}

# Create new differential after each incremental
# Allows: Base -> Incr -> Diff1 -> Diff2 -> ...
# Reduces storage and restore time
```

Example with monthly base + weekly incremental + daily differential:
```
Base (Feb 1)       [full DB]        [~500 MB]
├─ Incr (Feb 8)   [since Feb 1]     [~50 MB]
│  ├─ Diff (Feb 9) [since Feb 8]    [~5 MB]
│  ├─ Diff (Feb 10) [since Feb 8]   [~5 MB]
│  └─ Diff (Feb 11) [since Feb 8]   [~3 MB]
├─ Incr (Feb 15)  [since Feb 1]     [~60 MB]
│  └─ Diff (Feb 16) [since Feb 15]  [~4 MB]

Restore Feb 16 @ 10:00:
→ Base (500MB) + Incr (60MB) + Diff (4MB) = 564 MB processed
  vs. Base + 15 daily incrementals = 815 MB
  → 30% reduction!
```

---

### ✅ Tier 3: Add Backup Validation & Verification

#### Objective
Ensure backup integrity and verify recoverability.

#### Implementation

**1. Checksums & Signatures**

```python
def _finalize_backup_file(self, backup_path: Path):
    """Add checksum to backup file"""
    # Calculate checksums
    sha256 = self._calculate_sha256(backup_path)
    md5 = self._calculate_md5(backup_path)
    
    # Store in metadata
    metadata['checksums'] = {
        'sha256': sha256,
        'md5': md5,
        'calculated_at': datetime.now().isoformat()
    }
    
    # Optionally: Add signature if encryption enabled
    if PITR_CONFIG['backup_encryption_enabled']:
        metadata['signature'] = self._sign_backup(backup_path)
```

**2. Backup Verification**

```python
def verify_backup_integrity(backup_id: str) -> dict:
    """Verify backup file integrity"""
    backup = self.backup_manager.get_backup(backup_id)
    
    # Verify file exists
    if not backup['path'].exists():
        return {'valid': False, 'error': 'File not found'}
    
    # Verify checksums
    actual_sha256 = self._calculate_sha256(backup['path'])
    if actual_sha256 != backup['checksums']['sha256']:
        return {'valid': False, 'error': 'Checksum mismatch (file corrupted)'}
    
    # Verify metadata consistency
    if not self._verify_metadata_consistency(backup):
        return {'valid': False, 'error': 'Metadata inconsistent'}
    
    # Verify restorable (sample restore without writing)
    if not self._test_restore_capability(backup):
        return {'valid': False, 'error': 'Cannot parse/apply backup'}
    
    return {'valid': True, 'verified_at': datetime.now().isoformat()}
```

**3. Dry-Run Restore Test**

```python
def test_restore_capability(backup_id: str) -> dict:
    """Test if backup can be restored (dry run, non-destructive)"""
    backup = self.backup_manager.get_backup(backup_id)
    
    # Parse backup (SQL or JSON)
    changes = self._parse_backup_file(backup['path'], limit=100)
    
    # Validate SQL syntax (without executing)
    for change in changes:
        sql = self._generate_sql(change)
        if not self._validate_sql_syntax(sql):
            return {'valid': False, 'error': f'Invalid SQL: {sql}'}
    
    # Verify LSN ordering
    lsns = [c['lsn'] for c in changes]
    if lsns != sorted(lsns):
        return {'valid': False, 'error': 'LSN ordering violated'}
    
    return {'valid': True, 'sample_changes_verified': len(changes)}
```

---

### ✅ Tier 4: Smart Retention & Optimization

#### Objective
Intelligently clean up old backups while maintaining recovery capability.

#### Implementation

**Retention Policy:**
```python
RETENTION_POLICY = {
    'hourly': {'keep': 24, 'max_age_hours': 24},      # Keep last 24 hourly
    'daily': {'keep': 30, 'max_age_days': 30},        # Keep last 30 daily
    'weekly': {'keep': 12, 'max_age_weeks': 12},      # Keep last 12 weekly
    'monthly': {'keep': 12, 'max_age_months': 12},    # Keep last 12 monthly
    
    'min_backup_chain_length': 3,  # Always keep at least 3 levels
}
```

**Cleanup Algorithm:**
```python
def cleanup_old_backups(self):
    """Remove backups no longer needed per policy"""
    backups = self.backup_manager.list_all_backups()
    
    to_delete = []
    
    # Group by backup chain
    chains = self._group_by_chain(backups)
    
    for chain_id, chain_backups in chains.items():
        # Ensure minimum chain length
        if len(chain_backups) <= RETENTION_POLICY['min_backup_chain_length']:
            continue
        
        # Group by age category
        hourly = [b for b in chain_backups if self._is_recent(b, hours=1)]
        daily = [b for b in chain_backups if self._is_recent(b, days=1)]
        # ... etc
        
        # Keep only allowed number
        if len(hourly) > RETENTION_POLICY['hourly']['keep']:
            to_delete.extend(hourly[RETENTION_POLICY['hourly']['keep']:])
        # ... etc
    
    # Execute deletion
    for backup in to_delete:
        self._delete_backup(backup)
        print(f"Deleted old backup: {backup['filename']}")
```

---

### ✅ Tier 5: Parallel Change Application

#### Objective
Speed up restore by applying changes in parallel when possible.

#### Implementation

```python
def _apply_changes_parallel(
    self,
    changes: List[dict],
    target_db: str,
    num_workers: int = 4
) -> int:
    """
    Apply changes using thread pool for better performance
    Respects LSN ordering and transaction boundaries
    """
    from concurrent.futures import ThreadPoolExecutor
    from queue import Queue
    import threading
    
    # Group changes by independent tables (no FK constraints between groups)
    change_groups = self._partition_changes_by_table(changes)
    
    applied = 0
    
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = []
        
        for group in change_groups:
            # Each table group can be processed independently
            future = executor.submit(
                self._apply_change_group,
                group,
                target_db
            )
            futures.append(future)
        
        # Wait for all to complete
        for future in futures:
            group_applied = future.result()
            applied += group_applied
    
    return applied
```

---

## Implementation Roadmap

### Phase 1: Foundation (Weeks 1-2)
- [ ] Add backup lineage metadata
- [ ] Implement embedded metadata in backup files
- [ ] Update backup catalog schema
- [ ] Add `parent_backup_id` and chain tracking

### Phase 2: Restoration Chain (Weeks 2-3)
- [ ] Implement `build_restore_chain()` function
- [ ] Update `restore_to_timestamp()` to use chains
- [ ] Add incremental-only restore path
- [ ] Update CLI with chain information display

### Phase 3: Validation (Weeks 3-4)
- [ ] Add checksum calculation and verification
- [ ] Implement dry-run restore testing
- [ ] Add backup integrity checks
- [ ] Create backup health monitoring command

### Phase 4: Optimization (Weeks 4-5)
- [ ] Implement multi-level backup strategy
- [ ] Add differential backup creation
- [ ] Optimize SQL parsing for restore
- [ ] Add parallel change application

### Phase 5: Management (Weeks 5-6)
- [ ] Implement smart retention policies
- [ ] Add automatic cleanup scheduling
- [ ] Create backup statistics/reporting
- [ ] Add backup pruning CLI

---

## Recommended Quick Wins (Can Do Now)

1. **Embed metadata in SQL files** (1 hour)
   - Parse and extract at restore time
   - Ensures metadata stays with file

2. **Add backup lineage tracking** (2 hours)
   - Simple JSON field additions
   - Enable chain building

3. **Implement backup chaining restore** (3 hours)
   - Build chain of backups
   - Apply in order

4. **Add integrity verification** (2 hours)
   - SHA256 checksum calculation
   - File validation before restore

---

## Example: Restored Incremental Restore Workflow

**Before (Base-Only):**
```bash
$ python restore_cli.py restore-to-timestamp "2026-02-15 23:30:00" --db test_restore
Loading backups...
Found base backup: base_snapshot_20260215_123658.dump (500 MB)
Restoring base... [########################################] 100%
Applying 1250 incremental changes... [#######################     ] 85%
ERROR: Incremental backup missing or corrupted!
Restore FAILED
```

**After (Incremental Chain):**
```bash
$ python restore_cli.py restore-to-timestamp "2026-02-15 23:30:00" --db test_restore
Finding recovery point... ✓
Building restore chain...
  1. base_snapshot_20260215_123658.dump (500 MB, base)
  2. cdc_backup_20260215_123658.sql (50 MB, incr)
  3. cdc_backup_20260215_140000.sql (45 MB, incr)
  4. cdc_backup_20260215_200000.sql (40 MB, incr [filtered to 23:30])
Total: 635 MB across 4 backups

Verifying backup chain... ✓
Restoring chain:
  1. Restoring base... [########################################] 100%
  2. Applying changes (1/1250 changes)... [###########      ] 45%
  3. Applying changes (250/1250 changes)... [################      ] 65%
  4. Applying changes (500/1250 changes)... [#####################] 100%

✓ Successfully restored to 2026-02-15 23:30:00
  - 4 backups applied
  - 1,250 changes processed
  - Restore time: 3m 45s
```

---

## Summary

The current CDC system provides a solid foundation with LSN-tracked incremental backups. Key improvements to make incremental backups truly restorable:

1. ✅ **Track backup chains** - Establish parent-child relationships
2. ✅ **Embed metadata** - Keep backup info with backup files
3. ✅ **Enable incremental chain restore** - Apply multiple backups in sequence
4. ✅ **Add verification** - Validate backup integrity before restore
5. ✅ **Implement differential levels** - Reduce storage and restore time
6. ✅ **Smart retention** - Keep necessary backups, clean old ones

These changes transform the system from "base backup required" to a true incremental backup solution where any chain of backups can be restored independently, and backups are self-contained and verifiable.

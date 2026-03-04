1. **Run the CDC processor** – starts capturing changes and writing backups.  If a
     base snapshot is missing or stale, `main.py` will automatically create one on
     startup.  The processor will then generate incremental `.sql` files containing
     only the row changes.
2. **Restore the database** by replaying backups:
     * use the CLI helpers (`restore_cli.py restore` or `restore_cli.py restore-chain`)
         to automatically locate the base plus all required incrementals and apply
         them in order (dry-run mode is available with `--dry-run`).
     * or, if you want a single SQL script, run `combine_backups.py` to concatenate
         the base and incremental files into `full_restore.sql` and then run
         `psql -f full_restore.sql` against the target database.

     example (dry run):

     ```powershell
     python restore_cli.py restore-chain \
             --timestamp "2026-03-03 19:00:00" \
             --target-db test_restore \
             --dry-run --verify
     ```

     or generate a combined script manually:

     ```powershell
     python combine_backups.py \
             --timestamp "2026-03-03 19:00:00" \
             --output full_restore.sql
     psql -h <host> -p <port> -U <user> -d test_restore -f full_restore.sql
     ```
# Quick Start Guide - CDC with PITR

## 5-Minute Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure PostgreSQL

Check if logical replication is enabled:

```sql
SHOW wal_level;
-- Should return 'logical'
```

If not, edit `postgresql.conf`:
```conf
wal_level = logical
max_replication_slots = 10
max_wal_senders = 10
```

Then restart PostgreSQL.

### 3. Create Replication Slot

### 4. Create an Initial Base Snapshot

Before starting CDC, generate a full snapshot of your schema/data to restore onto later:

```bash
python restore_cli.py base-backup --db test
```

### 5. Start CDC Capture

```bash
python main_pitr.py
```

That's it! CDC is now capturing changes incrementally with No-WAL PITR support.

## Testing the System

### Make Some Changes

In another terminal, connect to PostgreSQL and make changes:

```sql
-- Connect to database
psql -U postgres -d test

-- Create test table
CREATE TABLE test_users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(100)
);

-- Insert data
INSERT INTO test_users (name, email) VALUES ('Alice', 'alice@example.com');
INSERT INTO test_users (name, email) VALUES ('Bob', 'bob@example.com');

-- Update data
UPDATE test_users SET email = 'alice.new@example.com' WHERE name = 'Alice';

-- Delete data
DELETE FROM test_users WHERE name = 'Bob';
```

### View Captured Changes

Check the CDC logs:

```bash
# View last 20 lines
Get-Content cdc_changes.log -Tail 20

# Or on Linux/Mac
tail -20 cdc_changes.log
```

### List Backups

```bash
python restore_cli.py list-backups
```

### List Recovery Points

```bash
python restore_cli.py list-recovery-points
```

### Preview a Restore

```bash
python restore_cli.py preview --timestamp "2024-02-01 18:00:00"
```

### Perform a Test Restore

```bash
# Create a test database first
psql -U postgres -c "CREATE DATABASE test_restore;"

# Copy schema from source
pg_dump -U postgres -d test --schema-only | psql -U postgres -d test_restore

# Perform restore (dry run first)
python restore_cli.py restore --timestamp "2024-02-01 18:00:00" --target-db test_restore --dry-run

# Actual restore
python restore_cli.py restore --timestamp "2024-02-01 18:00:00" --target-db test_restore --yes
```

### Verify Restored Data

```sql
-- Connect to restored database
psql -U postgres -d test_restore

-- Check data
SELECT * FROM test_users;
```

## Common Commands

### CDC Operations

```bash
# Start CDC with default settings
python main_pitr.py

# Show statistics
python main_pitr.py --stats

# Use custom replication slot
python main_pitr.py --slot-name my_custom_slot
```

### Restore Operations

```bash
# 1. Create a base snapshot (Initial setup)
python restore_cli.py base-backup --db test

# 2. List all backups
python restore_cli.py list-backups

# 3. List backups in time range
python restore_cli.py list-backups --start-time "2024-02-01 10:00:00"

# 4. List recovery points
python restore_cli.py list-recovery-points

# 5. Preview restore
python restore_cli.py preview --timestamp "2024-02-01 14:30:00"

# 6. Restore (dry run)
python restore_cli.py restore --timestamp "2024-02-01 14:30:00" --target-db test_restore --dry-run

# 7. Restore (actual)
python restore_cli.py restore --timestamp "2024-02-01 14:30:00" --target-db test_restore --yes

# Restore specific tables
python restore_cli.py restore --timestamp "2024-02-01 14:30:00" --target-db test_restore --tables users orders --yes

## Directory Structure

After running, you'll have:

```
CDC/
├── cdc_backups/              # Backup files (compressed)
├── backup_metadata/          # Backup catalog and metadata
├── transaction_logs/         # Transaction tracking logs
├── cdc_changes.log          # CDC processor log
├── pitr_backup.log          # Backup manager log
├── pitr_restore.log         # Restore operations log
└── last_lsn.txt             # Last processed LSN
```

## Troubleshooting

### "Replication slot already exists"

This is normal. The slot was already created. Just run:
```bash
python main_pitr.py
```

### "Permission denied" on PostgreSQL

Make sure your user has replication permissions:
```sql
ALTER USER postgres WITH REPLICATION;
```

### "No recovery points found"

You need to make some changes first and let CDC capture them. The system only creates recovery points for committed transactions.

### CDC not capturing changes

1. Check if CDC is running: `python main_pitr.py --stats`
2. Verify replication slot exists: `SELECT * FROM pg_replication_slots;`
3. Check logs: `cat cdc_changes.log`

## Next Steps

- Read the full [README_PITR.md](README_PITR.md) for detailed documentation
- Configure retention policies in `services/pitr_config.py`
- Set up automated backups of the backup directory
- Test restore procedures regularly

## Production Checklist

- [ ] Configure appropriate retention policies
- [ ] Set up monitoring for disk space
- [ ] Test restore procedures
- [ ] Document recovery runbooks
- [ ] Set up backup of backup directory to remote storage
- [ ] Configure log rotation
- [ ] Test failover scenarios
- [ ] Monitor CDC lag

"""
PITR Backup Manager
Manages CDC backups with LSN tracking and transaction consistency
"""

import json
import gzip
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import threading
from collections import defaultdict
import psycopg2.extensions

from .pitr_config import PITR_CONFIG, DB_CONFIG
from .TransactionLogManager import TransactionLogManager
from .EnhancedBackupManager import (
    EnhancedBackupMetadata,
    BackupChainBuilder,
    BackupIntegrityValidator,
)


class PITRBackupManager:
    """
    Manages CDC backups with LSN tracking for Point-in-Time Recovery.
    Stores changes with full metadata for transaction-consistent recovery.
    """
    
    def __init__(self, backup_dir: str = None, transaction_manager: TransactionLogManager = None):
        self.backup_dir = Path(backup_dir or PITR_CONFIG['backup_dir'])
        self.metadata_dir = Path(PITR_CONFIG['metadata_dir'])
        
        # Create directories
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger = self._configure_logger()
        self.transaction_manager = transaction_manager or TransactionLogManager()
        
        # Buffering for batch writes
        self.change_buffer: List[dict] = []
        self.buffer_lock = threading.Lock()
        self.last_flush_time = datetime.now()
        
        # Current backup file
        self.current_backup_file = None
        self.current_backup_metadata = None
        self._initialize_backup_file()
        
        # Background flush thread
        self.stop_requested = False
        self.flush_thread = threading.Thread(target=self._background_flush_loop, daemon=True)
        self.flush_thread.start()
        
        # Backup catalog
        self.backup_catalog = self._load_backup_catalog()

        # Enhanced manager integration (optional)
        try:
            # Validator for checksums/verification
            self.validator = BackupIntegrityValidator(self)
            # Chain builder initialized with current catalog
            self.chain_builder = BackupChainBuilder(self.backup_catalog)
        except Exception as e:
            # If the enhanced module is not present or fails, continue gracefully
            self.logger.warning(f"EnhancedBackupManager not available: {e}")
            self.validator = None
            self.chain_builder = None
    
    def _configure_logger(self) -> logging.Logger:
        """Configure logger for backup manager"""
        logger = logging.getLogger("PITRBackupManager")
        logger.setLevel(getattr(logging, PITR_CONFIG['log_level']))
        
        if not logger.handlers:
            handler = logging.FileHandler(
                self.backup_dir / PITR_CONFIG['log_file']
            )
            formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def _initialize_backup_file(self):
        """Initialize a new backup file"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        format_ext = PITR_CONFIG['backup_format']
        filename = f"cdc_backup_{timestamp}.{format_ext}"
        
        if PITR_CONFIG['compression_enabled']:
            filename += '.gz'
        
        self.current_backup_file = self.backup_dir / filename
        
        # Write SQL headers if format is SQL and file is new
        if format_ext == 'sql' and not self.current_backup_file.exists():
            self._write_sql_header()
        
        self.current_backup_metadata = {
            'backup_id': timestamp,
            'filename': filename,
            'start_time': datetime.now().isoformat(),
            'start_lsn': None,
            'end_lsn': None,
            'end_time': None,
            'changes_count': 0,
            'tables_affected': set(),
            'transactions': set(),
            'format': PITR_CONFIG['backup_format'],
            'compressed': PITR_CONFIG['compression_enabled']
        }
        
        self.logger.info(f"Initialized new backup file: {filename}")
    
    def track_change(
        self,
        lsn: str,
        txid: int,
        timestamp: datetime,
        table_name: str,
        operation: str,
        data: dict,
        old_data: dict = None
    ):
        """
        Track a CDC change with full metadata
        
        Args:
            lsn: Log Sequence Number
            txid: Transaction ID
            timestamp: Change timestamp
            table_name: Affected table name
            operation: Operation type (INSERT, UPDATE, DELETE)
            data: New/current data
            old_data: Old data (for UPDATE/DELETE)
        """
        change_record = {
            'lsn': lsn,
            'txid': txid,
            'timestamp': timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp,
            'table': table_name,
            'operation': operation,
            'data': data,
            'old_data': old_data
        }
        
        with self.buffer_lock:
            self.change_buffer.append(change_record)
            self.logger.info(f"Buffered change for {table_name}, buffer size: {len(self.change_buffer)}")
            
            # Update metadata
            if self.current_backup_metadata['start_lsn'] is None:
                self.current_backup_metadata['start_lsn'] = lsn
            
            self.current_backup_metadata['end_lsn'] = lsn
            self.current_backup_metadata['changes_count'] += 1
            self.current_backup_metadata['tables_affected'].add(table_name)
            self.current_backup_metadata['transactions'].add(txid)
            
            # Update transaction manager
            self.transaction_manager.add_change_to_transaction(txid, table_name)
            
            # Check if we should flush
            should_flush = (
                len(self.change_buffer) >= PITR_CONFIG['batch_size'] or
                (datetime.now() - self.last_flush_time).seconds >= PITR_CONFIG['flush_interval_seconds']
            )
            
            if should_flush:
                self._flush_buffer()
    
    def _flush_buffer(self):
        """Flush buffered changes to disk"""
        if not self.change_buffer:
            return
        
        try:
            # Check if we need to rotate backup file
            if self._should_rotate_backup():
                self._rotate_backup_file()
            
            # Write changes
            format_type = PITR_CONFIG['backup_format']
            if format_type == 'jsonl':
                self._write_jsonl(self.change_buffer)
            elif format_type == 'sql':
                self._write_sql(self.change_buffer)
            else:
                self._write_json(self.change_buffer)
            
            self.logger.info(f"Successfully flushed {len(self.change_buffer)} changes to disk")
            
            self.change_buffer.clear()
            self.last_flush_time = datetime.now()
        
        except Exception as e:
            self.logger.error(f"Error flushing buffer: {e}")

    def _generate_sql(self, change: dict) -> str:
        """Generate an executable SQL statement from a change record"""
        table = change['table']
        op = change['operation']
        data = change['data']
        old_data = change.get('old_data')
        
        # Helper to format values for SQL
        def fmt(val):
            return psycopg2.extensions.adapt(val).getquoted().decode('utf-8')

        if op == 'INSERT':
            cols = ", ".join(data.keys())
            vals = ", ".join(fmt(v) for v in data.values())
            return f"INSERT INTO {table} ({cols}) VALUES ({vals});"
            
        elif op == 'UPDATE':
            # Identify "primary key" or identifying columns
            # If old_data is present, we use it for the WHERE clause
            # Otherwise, we assume the first column is the key (common for CDC)
            id_cols = old_data if old_data else data
            pk_col = list(id_cols.keys())[0]
            pk_val = id_cols[pk_col]
            
            sets = ", ".join(f"{k} = {fmt(v)}" for k, v in data.items() if k != pk_col)
            if not sets: # Might happen if only PK changed or no other columns
                return f"-- SKIP UPDATE on {table}: No columns to set"
                
            return f"UPDATE {table} SET {sets} WHERE {pk_col} = {fmt(pk_val)};"
            
        elif op == 'DELETE':
            id_cols = old_data if old_data else data
            pk_col = list(id_cols.keys())[0]
            pk_val = id_cols[pk_col]
            return f"DELETE FROM {table} WHERE {pk_col} = {fmt(pk_val)};"
            
        return f"-- UNKNOWN OPERATION: {op}"

    def _write_sql_header(self):
        """Write standard PostgreSQL headers to the SQL backup file"""
        headers = [
            "-- PostgreSQL CDC Incremental Backup",
            "-- RESTORE INSTRUCTION: Use 'psql -f <filename>' to restore this file.",
            "-- DO NOT USE pg_restore.",
            f"-- Generated: {datetime.now().isoformat()}",
            "SET client_encoding = 'UTF8';",
            "SET standard_conforming_strings = on;",
            "SET check_function_bodies = false;",
            "SET xmloption = content;",
            "SET client_min_messages = warning;",
            "SET row_security = off;",
            "SET search_path = public, pg_catalog;",
            "\n"
        ]
        
        open_func = gzip.open if PITR_CONFIG['compression_enabled'] else open
        mode = 'wt' if PITR_CONFIG['compression_enabled'] else 'w'
        
        with open_func(self.current_backup_file, mode, encoding='utf-8') as f:
            f.write("\n".join(headers))

    def _write_sql(self, changes: List[dict]):
        """Write changes as SQL comments and statements wrapped in a transaction"""
        open_func = gzip.open if PITR_CONFIG['compression_enabled'] else open
        mode = 'at' if PITR_CONFIG['compression_enabled'] else 'a'
        
        with open_func(self.current_backup_file, mode, encoding='utf-8') as f:
            f.write("BEGIN;\n\n")
            for change in changes:
                sql = self._generate_sql(change)
                # Combined metadata comment for PITR parsing
                meta = f"-- LSN: {change['lsn']}, TXID: {change['txid']}, TS: {change['timestamp']}"
                f.write(f"{meta}\n{sql}\n\n")
            f.write("COMMIT;\n\n")
    
    def _write_jsonl(self, changes: List[dict]):
        """Write changes in JSON Lines format"""
        open_func = gzip.open if PITR_CONFIG['compression_enabled'] else open
        mode = 'at' if PITR_CONFIG['compression_enabled'] else 'a'
        
        with open_func(self.current_backup_file, mode, encoding='utf-8') as f:
            for change in changes:
                f.write(json.dumps(change) + '\n')
    
    def _write_json(self, changes: List[dict]):
        """Write changes as JSON array (Warning: inefficient for large backups)"""
        # Ideally, use jsonl for incremental backups
        # This implemention seeks end of file and appends to array
        # But for robustness we often re-read. 
        # To strictly follow "only changes" without full rewrite, we should recommend jsonl.
        
        # If the file doesn't exist, start array
        if not self.current_backup_file.exists():
            with open(self.current_backup_file, 'w', encoding='utf-8') as f:
                f.write('[\n')
                # Write first item
                if changes:
                    json.dump(changes[0], f)
                    for change in changes[1:]:
                        f.write(',\n')
                        json.dump(change, f)
                f.write('\n]')
                return

        # If it exists, we need to append
        # This is tricky with valid JSON [ ... ]
        # We will strip the last ']' and append
        try:
            with open(self.current_backup_file, 'r+', encoding='utf-8') as f:
                f.seek(0, 2) # Go to end
                pos = f.tell()
                # Search backwards for ']'
                # This is a simplified approach
                while pos > 0:
                    pos -= 1
                    f.seek(pos)
                    char = f.read(1)
                    if char == ']':
                        f.seek(pos) # Position before ']'
                        break
                
                # Check if we found it
                if pos > 0:
                    for change in changes:
                        f.write(',\n')
                        json.dump(change, f)
                    f.write('\n]')
                else:
                    # Fallback if structure is weird: Append as if it was jsonl?
                    # Or just rewrite (old behavior) is safer but slower
                    self.logger.warning("Could not append to JSON efficiently, rewriting file.")
                    self._rewrite_json_fallback(changes)
                    
        except Exception as e:
            self.logger.error(f"Error appending (JSON): {e}")

    def _rewrite_json_fallback(self, changes):
        """Fallback to rewrite full file"""
        open_func = gzip.open if PITR_CONFIG['compression_enabled'] else open
        mode = 'rt' if PITR_CONFIG['compression_enabled'] else 'r'
        
        existing = []
        try:
            with open_func(self.current_backup_file, mode, encoding='utf-8') as f:
                existing = json.load(f)
        except:
            pass
            
        existing.extend(changes)
        
        mode = 'wt' if PITR_CONFIG['compression_enabled'] else 'w'
        with open_func(self.current_backup_file, mode, encoding='utf-8') as f:
            json.dump(existing, f, indent=2)
    
    def _should_rotate_backup(self) -> bool:
        """Check if backup file should be rotated"""
        if not self.current_backup_file.exists():
            return False
        
        # Check file size
        size_mb = self.current_backup_file.stat().st_size / (1024 * 1024)
        if size_mb >= PITR_CONFIG['max_backup_size_mb']:
            return True
        
        # Check if it's a new day
        current_date = datetime.now().strftime('%Y%m%d')
        backup_date = self.current_backup_metadata['backup_id'][:8]
        if current_date != backup_date:
            return True
        
        return False
    
    def _rotate_backup_file(self):
        """Rotate to a new backup file"""
        # Flush any remaining changes
        if self.change_buffer:
            self._flush_buffer()
        
        # Finalize current backup metadata
        self._finalize_backup_metadata()
        
        # Initialize new backup file
        self._initialize_backup_file()
        
        self.logger.info("Rotated to new backup file")
    
    def _finalize_backup_metadata(self):
        """Finalize and save backup metadata"""
        self.current_backup_metadata['end_time'] = datetime.now().isoformat()
        self.current_backup_metadata['tables_affected'] = list(
            self.current_backup_metadata['tables_affected']
        )
        self.current_backup_metadata['transactions'] = list(
            self.current_backup_metadata['transactions']
        )

        # Populate lineage information (parent/base/chain depth)
        if self.backup_catalog:
            try:
                latest = max(
                    self.backup_catalog,
                    key=lambda b: b.get('end_time', b.get('start_time'))
                )
                self.current_backup_metadata['parent_backup_id'] = latest.get('backup_id')
                self.current_backup_metadata['base_backup_id'] = latest.get('base_backup_id', latest.get('backup_id'))
                self.current_backup_metadata['chain_depth'] = latest.get('chain_depth', 0) + 1
            except Exception:
                # Fallback if catalog entries lack times
                self.current_backup_metadata['parent_backup_id'] = None
                self.current_backup_metadata['base_backup_id'] = self.current_backup_metadata['backup_id']
                self.current_backup_metadata['chain_depth'] = 0
        else:
            # No previous backups: this is a base
            self.current_backup_metadata['backup_type'] = 'base'
            self.current_backup_metadata['parent_backup_id'] = None
            self.current_backup_metadata['base_backup_id'] = self.current_backup_metadata['backup_id']
            self.current_backup_metadata['chain_depth'] = 0

        # Compute size and checksums if validator available
        try:
            backup_path = self.backup_dir / self.current_backup_metadata['filename']
            if backup_path.exists():
                try:
                    self.current_backup_metadata['size_bytes'] = backup_path.stat().st_size
                except Exception:
                    self.current_backup_metadata['size_bytes'] = None

            if self.validator and backup_path.exists():
                checksums = self.validator.calculate_checksums(backup_path)
                self.current_backup_metadata['checksums'] = checksums
                # Run full verification and store results
                try:
                    is_valid, errors = self.validator.verify_backup_file(
                        self.current_backup_metadata['backup_id'],
                        self.current_backup_metadata
                    )
                    self.current_backup_metadata['verified'] = is_valid
                    self.current_backup_metadata['verification_errors'] = errors
                except Exception as e:
                    self.logger.warning(f"Backup verification failed: {e}")
                    self.current_backup_metadata['verified'] = False
                    self.current_backup_metadata['verification_errors'] = [str(e)]
        except Exception as e:
            self.logger.warning(f"Error while computing checksums/size: {e}")
        
        # Save metadata
        metadata_file = self.metadata_dir / f"{self.current_backup_metadata['backup_id']}_metadata.json"
        with open(metadata_file, 'w') as f:
            json.dump(self.current_backup_metadata, f, indent=2)
        
        # Update catalog
        self.backup_catalog.append(self.current_backup_metadata.copy())
        self._save_backup_catalog()
        
        self.logger.info(
            f"Finalized backup {self.current_backup_metadata['backup_id']} "
            f"({self.current_backup_metadata['changes_count']} changes)"
        )
    
    def _load_backup_catalog(self) -> List[dict]:
        """Load backup catalog from disk"""
        catalog_file = self.metadata_dir / "backup_catalog.json"
        
        if catalog_file.exists():
            try:
                with open(catalog_file, 'r') as f:
                    catalog = json.load(f)
                self.logger.info(f"Loaded backup catalog with {len(catalog)} entries")
                return catalog
            except Exception as e:
                self.logger.error(f"Error loading backup catalog: {e}")
        
        return []
    
    def _check_pg_tools(self):
        """Check if required PostgreSQL tools are available"""
        import subprocess
        try:
            subprocess.run(['pg_dump', '--version'], capture_output=True, check=True)
            subprocess.run(['psql', '--version'], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def get_latest_base_backup(self, before_timestamp: datetime = None) -> Optional[dict]:
        """
        Get the latest base backup metadata
        
        Args:
            before_timestamp: Optional timestamp to limit the search (find latest BEFORE this time)
            
        Returns:
            Base backup metadata or None
        """
        base_backups = []
        
        # Scan metadata directory for base snapshots
        for file in self.metadata_dir.glob("base_snapshot_*_meta.json"):
            try:
                with open(file, 'r') as f:
                    meta = json.load(f)
                    base_backups.append(meta)
            except Exception as e:
                self.logger.error(f"Error reading metadata file {file}: {e}")
        
        if not base_backups:
            return None
            
        # Sort by timestamp (newest first)
        base_backups.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # Filter if timestamp provided
        if before_timestamp:
            for backup in base_backups:
                backup_time = datetime.fromisoformat(backup['timestamp'])
                if backup_time < before_timestamp:
                    return backup
            return None
        
        return base_backups[0]


    def create_base_backup(self, target_db: str, output_path: str = None) -> dict:
        """
        Create a full base snapshot using pg_dump
        
        Args:
            target_db: Database to back up
            output_path: Optional path for the snapshot file
            
        Returns:
            Snapshot metadata
        """
        import subprocess
        
        if not self._check_pg_tools():
            raise RuntimeError("pg_dump/psql not found. Please ensure PostgreSQL bin folder is in your PATH.")
            
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if not output_path:
            ext = 'dump' if PITR_CONFIG.get('base_backup_format') == 'custom' else 'sql'
            output_path = self.backup_dir / f"base_snapshot_{timestamp}.{ext}"
        else:
            output_path = Path(output_path)
            
        self.logger.info(f"Creating base backup for database {target_db}...")
        
        cmd = [
            'pg_dump',
            '-U', DB_CONFIG.get('user', 'postgres'),
            '-h', DB_CONFIG.get('host', '127.0.0.1'),
            '-p', str(DB_CONFIG.get('port', 5432)),
            '--clean', '--if-exists', # Add clean commands for easier restore
            '--schema-only', # Often preferred for CDC targets, or remove for full
            '-F', 'c' if PITR_CONFIG.get('base_backup_format') == 'custom' else 'p', # Custom format for pg_restore
            '-f', str(output_path),
            target_db
        ]
        
        # Note: This assumes pg_dump can access via PGPASSWORD or .pgpass
        # In a real environment, we'd handle authentication more securely
        env = os.environ.copy()
        if DB_CONFIG.get('password'):
            env['PGPASSWORD'] = DB_CONFIG['password']
            
        try:
            subprocess.run(cmd, env=env, check=True, capture_output=True)
            
            # Verify file size
            if not output_path.exists() or output_path.stat().st_size == 0:
                if output_path.exists():
                    output_path.unlink()
                raise RuntimeError("pg_dump created an empty file (backup failed silently?)")
                
            snapshot_metadata = {
                'type': 'base_snapshot',
                'timestamp': datetime.now().isoformat(),
                'database': target_db,
                'filename': output_path.name,
                'path': str(output_path)
            }
            
            # Save metadata
            meta_file = self.metadata_dir / f"base_snapshot_{timestamp}_meta.json"
            with open(meta_file, 'w') as f:
                json.dump(snapshot_metadata, f, indent=2)
                
            self.logger.info(f"Base backup created successfully: {output_path} ({output_path.stat().st_size} bytes)")
            return snapshot_metadata
            
        except subprocess.CalledProcessError as e:
            if output_path.exists():
                output_path.unlink()
            error_msg = e.stderr.decode()
            self.logger.error(f"Error creating base backup: {error_msg}")
            raise RuntimeError(f"pg_dump failed: {error_msg}")

    def _save_backup_catalog(self):
        """Save backup catalog to disk"""
        catalog_file = self.metadata_dir / "backup_catalog.json"
        
        try:
            with open(catalog_file, 'w') as f:
                json.dump(self.backup_catalog, f, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving backup catalog: {e}")
    
    def create_backup_point(self, label: str, description: str = "") -> dict:
        """
        Create a named backup point for easy recovery
        
        Args:
            label: Backup point label
            description: Optional description
        
        Returns:
            Backup point metadata
        """
        # Flush current buffer
        with self.buffer_lock:
            self._flush_buffer()
        
        backup_point = {
            'label': label,
            'description': description,
            'timestamp': datetime.now().isoformat(),
            'lsn': self.current_backup_metadata['end_lsn'],
            'backup_id': self.current_backup_metadata['backup_id']
        }
        
        # Save backup point
        points_file = self.metadata_dir / "backup_points.json"
        points = []
        
        if points_file.exists():
            with open(points_file, 'r') as f:
                points = json.load(f)
        
        points.append(backup_point)
        
        with open(points_file, 'w') as f:
            json.dump(points, f, indent=2)
        
        self.logger.info(f"Created backup point: {label}")
        return backup_point
    
    def get_backup_metadata(self, backup_id: str) -> Optional[dict]:
        """Get metadata for a specific backup"""
        for backup in self.backup_catalog:
            if backup['backup_id'] == backup_id:
                return backup
        return None
    
    def list_backups_in_range(
        self, 
        start_time: datetime = None, 
        end_time: datetime = None
    ) -> List[dict]:
        """
        List backups within a time range
        
        Args:
            start_time: Start of range
            end_time: End of range
        
        Returns:
            List of backup metadata
        """
        matching_backups = []
        
        for backup in self.backup_catalog:
            backup_time = datetime.fromisoformat(backup['start_time'])
            
            if start_time and backup_time < start_time:
                continue
            if end_time and backup_time > end_time:
                continue
            
            matching_backups.append(backup)
        
        return sorted(matching_backups, key=lambda x: x['start_time'])
    
    def get_changes_from_backup(self, backup_id: str) -> List[dict]:
        """
        Read all changes from a specific backup file
        
        Args:
            backup_id: Backup ID
        
        Returns:
            List of change records
        """
        metadata = self.get_backup_metadata(backup_id)
        if not metadata:
            raise ValueError(f"Backup {backup_id} not found")
        
        backup_file = self.backup_dir / metadata['filename']
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup file {metadata['filename']} not found")
        
        open_func = gzip.open if metadata['compressed'] else open
        mode = 'rt'
        
        changes = []
        
        try:
            with open_func(backup_file, mode, encoding='utf-8') as f:
                if metadata['format'] == 'jsonl':
                    for line in f:
                        if line.strip():
                            changes.append(json.loads(line))
                elif metadata['format'] == 'sql':
                    changes = self._read_sql(f)
                else:
                    changes = json.load(f)
        except Exception as e:
            self.logger.error(f"Error reading backup {backup_id}: {e}")
            raise
        
        return changes

    def _read_sql(self, file_handle) -> List[dict]:
        """Parse SQL file back into change records for PITR processing"""
        changes = []
        current_meta = None
        
        import re
        # Pattern to match -- LSN: ..., TXID: ..., TS: ...
        meta_pattern = re.compile(r"-- LSN: (.*?), TXID: (.*?), TS: (.*)")
        
        for line in file_handle:
            line = line.strip()
            if not line:
                continue
                
            if line.startswith("-- LSN:"):
                match = meta_pattern.search(line)
                if match:
                    current_meta = {
                        'lsn': match.group(1),
                        'txid': int(match.group(2)),
                        'timestamp': match.group(3)
                    }
            elif current_meta and (line.startswith("INSERT") or line.startswith("UPDATE") or line.startswith("DELETE")):
                # For restoration, we mainly care about the LSN, TxID, and the SQL itself
                # We can store the SQL in a special field 'sql' which RestoreManager can use
                change = current_meta.copy()
                change['sql'] = line
                # We also try to extract the table name for filtering
                table_match = re.search(r"(?:INSERT INTO|UPDATE|DELETE FROM)\s+(\S+)", line, re.I)
                change['table'] = table_match.group(1) if table_match else 'unknown'
                # operation
                op_match = re.match(r"(INSERT|UPDATE|DELETE)", line, re.I)
                change['operation'] = op_match.group(1).upper() if op_match else 'UNKNOWN'
                
                changes.append(change)
                current_meta = None # Wait for next metadata comment
                
        return changes
    
    def cleanup_old_backups(self, retention_days: int = None):
        """
        Remove old backups based on retention policy
        
        Args:
            retention_days: Number of days to retain backups
        """
        retention_days = retention_days or PITR_CONFIG['retention_days']
        cutoff_time = datetime.now().timestamp() - (retention_days * 86400)
        
        removed_backups = []
        
        for backup in self.backup_catalog[:]:
            backup_time = datetime.fromisoformat(backup['start_time']).timestamp()
            
            if backup_time < cutoff_time:
                # Remove backup file
                backup_file = self.backup_dir / backup['filename']
                if backup_file.exists():
                    backup_file.unlink()
                
                # Remove metadata file
                metadata_file = self.metadata_dir / f"{backup['backup_id']}_metadata.json"
                if metadata_file.exists():
                    metadata_file.unlink()
                
                removed_backups.append(backup['backup_id'])
                self.backup_catalog.remove(backup)
        
        if removed_backups:
            self._save_backup_catalog()
            self.logger.info(f"Removed {len(removed_backups)} old backups")
        
        return removed_backups
    
    def get_statistics(self) -> dict:
        """Get backup statistics"""
        total_changes = sum(b['changes_count'] for b in self.backup_catalog)
        total_size = sum(
            (self.backup_dir / b['filename']).stat().st_size 
            for b in self.backup_catalog 
            if (self.backup_dir / b['filename']).exists()
        )
        
        return {
            'total_backups': len(self.backup_catalog),
            'total_changes': total_changes,
            'total_size_mb': total_size / (1024 * 1024),
            'current_backup_changes': self.current_backup_metadata['changes_count'],
            'buffered_changes': len(self.change_buffer)
        }
    
    def force_flush(self):
        """Force flush of buffered changes"""
        with self.buffer_lock:
            self._flush_buffer()
    
    def shutdown(self):
        """Graceful shutdown - flush and finalize"""
        self.logger.info("Shutting down PITR Backup Manager")
        self.stop_requested = True
        
        with self.buffer_lock:
            self._flush_buffer()
            self._finalize_backup_metadata()
        
        self.logger.info("Shutdown complete")

    def _background_flush_loop(self):
        """Background thread loop to flush changes periodically"""
        import time
        self.logger.info("Background flush thread started")
        while not self.stop_requested:
            try:
                time.sleep(PITR_CONFIG.get('background_flush_interval', 5))
                
                # Check if we have data or enough time has passed
                should_flush = False
                with self.buffer_lock:
                    if self.change_buffer and (datetime.now() - self.last_flush_time).seconds >= PITR_CONFIG['flush_interval_seconds']:
                        should_flush = True
                
                if should_flush:
                    self.logger.debug("Background flush triggered by interval")
                    self.force_flush()
            except Exception as e:
                self.logger.error(f"Error in background flush thread: {e}")

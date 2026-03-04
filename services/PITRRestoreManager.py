"""
PITR Restore Manager
Handles point-in-time restoration from CDC backups
"""

import json
import logging
import psycopg2
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from .pitr_config import PITR_CONFIG, DB_CONFIG
from .PITRBackupManager import PITRBackupManager
from .TransactionLogManager import TransactionLogManager


class PITRRestoreManager:
    """
    Manages point-in-time restoration from CDC backups.
    Ensures transaction-consistent recovery to specified timestamps.
    """
    
    def __init__(
        self, 
        backup_manager: PITRBackupManager = None,
        transaction_manager: TransactionLogManager = None
    ):
        self.backup_manager = backup_manager or PITRBackupManager()
        self.transaction_manager = transaction_manager or TransactionLogManager()
        self.logger = self._configure_logger()
    
    def _configure_logger(self) -> logging.Logger:
        """Configure logger for restore manager"""
        logger = logging.getLogger("PITRRestoreManager")
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.FileHandler("pitr_restore.log")
            formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def validate_restore_point(self, target_timestamp: datetime) -> Tuple[bool, str, Optional[dict]]:
        """
        Validate if a restore point is transaction-consistent
        
        Args:
            target_timestamp: Target restore timestamp
        
        Returns:
            Tuple of (is_valid, message, recovery_point)
        """
        # Find the nearest committed transaction before target time
        recovery_points = self.transaction_manager.get_consistent_recovery_points(
            end_time=target_timestamp
        )
        
        if not recovery_points:
            return False, "No recovery points found before target timestamp", None
        
        # Get the last committed transaction before target
        nearest_point = recovery_points[-1]
        point_time = datetime.fromisoformat(nearest_point['timestamp'])
        
        # Check if there are active transactions at target time
        active_txs = self.transaction_manager.get_active_transactions()
        
        if active_txs:
            self.logger.warning(
                f"Found {len(active_txs)} active transactions. "
                f"Will restore to last committed transaction."
            )
        
        time_diff = (target_timestamp - point_time).total_seconds()
        
        return True, f"Valid recovery point found ({time_diff:.1f}s before target)", nearest_point
    
    def preview_restore(self, target_timestamp: datetime) -> dict:
        """
        Preview what a restore operation would do
        
        Args:
            target_timestamp: Target restore timestamp
        
        Returns:
            Dictionary with restore preview information
        """
        is_valid, message, recovery_point = self.validate_restore_point(target_timestamp)
        
        if not is_valid:
            return {
                'valid': False,
                'message': message,
                'recovery_point': None
            }
        
        # Find relevant backups
        backups = self.backup_manager.list_backups_in_range(
            end_time=datetime.fromisoformat(recovery_point['timestamp'])
        )
        
        # Calculate statistics
        total_changes = sum(b['changes_count'] for b in backups)
        tables_affected = set()
        for backup in backups:
            tables_affected.update(backup.get('tables_affected', []))
        
        return {
            'valid': True,
            'message': message,
            'recovery_point': recovery_point,
            'target_timestamp': target_timestamp.isoformat(),
            'actual_restore_timestamp': recovery_point['timestamp'],
            'backups_to_process': len(backups),
            'total_changes_to_apply': total_changes,
            'tables_affected': list(tables_affected),
            'backup_ids': [b['backup_id'] for b in backups]
        }
    
    def restore_to_timestamp(
        self, 
        target_timestamp: datetime,
        target_db: str = None,
        tables: List[str] = None,
        dry_run: bool = False
    ) -> dict:
        """
        Restore database to a specific point in time
        
        Args:
            target_timestamp: Target restore timestamp
            target_db: Target database name (if None, uses source DB - DANGEROUS!)
            tables: List of specific tables to restore (if None, restores all)
            dry_run: If True, only simulate the restore
        
        Returns:
            Dictionary with restore results
        """
        self.logger.info(f"Starting PITR restore to {target_timestamp}")
        
        # Validate restore point
        is_valid, message, recovery_point = self.validate_restore_point(target_timestamp)
        
        if not is_valid:
            self.logger.error(f"Invalid restore point: {message}")
            return {
                'success': False,
                'error': message
            }
        
        self.logger.info(f"Restore point validated: {message}")
        
        # Get preview
        preview = self.preview_restore(target_timestamp)
        
        # CHECK FOR BASE BACKUP
        base_backup = self.backup_manager.get_latest_base_backup(before_timestamp=target_timestamp)
        
        if dry_run:
            self.logger.info("Dry run mode - no changes will be made")
            if base_backup:
                print(f"      [Dry Run] Would restore base backup: {base_backup['filename']}")
            else:
                print("      [Dry Run] WARNING: No base backup found before target time!")
                
            return {
                'success': True,
                'dry_run': True,
                'preview': preview
            }
        
        # 1. Restore Base Backup
        if base_backup:
            # If tables are specified, we might want to skip full base restore or use --table filters
            # For now, we assume base restore is global
            if tables:
                 self.logger.warning("Table filtering enabled but restoring full base backup first. This might be slow.")
            
            try:
                self._restore_base_backup(base_backup, target_db or DB_CONFIG['dbname'])
            except Exception as e:
                self.logger.error(f"Failed to restore base backup: {e}")
                return {'success': False, 'error': f"Base restore failed: {e}"}
        else:
            self.logger.warning("No base backup found! Proceeding with incremental only (might be incomplete).")
        
        # 2. Apply Incremental Changes
        changes_to_apply = self._collect_changes_for_restore(
            recovery_point,
            tables
        )
        
        self.logger.info(f"Collected {len(changes_to_apply)} changes to apply")
        
        # Apply changes to target database
        try:
            applied_count = self._apply_changes(
                changes_to_apply,
                target_db or DB_CONFIG['dbname'],
                tables
            )
            
            self.logger.info(f"Successfully applied {applied_count} changes")
            
            return {
                'success': True,
                'recovery_point': recovery_point,
                'changes_applied': applied_count,
                'tables_restored': list(preview['tables_affected']),
                'restore_timestamp': recovery_point['timestamp'],
                'base_backup_restored': base_backup['filename'] if base_backup else None
            }
        
        except Exception as e:
            self.logger.error(f"Error during restore: {e}")
            return {
                'success': False,
                'error': str(e)
            }
            
    def _restore_base_backup(self, metadata: dict, target_db: str):
        """
        Restore a base backup using pg_restore
        """
        import subprocess
        import os
        
        path = metadata['path']
        self.logger.info(f"Restoring base backup from {path} to {target_db}...")
        
        if not os.path.exists(path):
            raise FileNotFoundError(f"Base backup file not found: {path}")
            
        if os.path.getsize(path) == 0:
            raise ValueError(f"Base backup file is empty: {path}")

        # Determine command based on file extension/format
        # metadata should strictly have 'filename' or 'path'
        if path.endswith('.sql'):
            # Use psql
            self.logger.info(f"Detected SQL format. Using psql for restore.")
            cmd = [
                'psql',
                '-h', DB_CONFIG['host'],
                '-p', str(DB_CONFIG['port']),
                '-U', DB_CONFIG['user'],
                '-d', target_db,
                '-f', path
            ]
        else:
            # Assume custom format -> pg_restore
            # Check if it's actually a custom dump ( pg_restore -l )
            # Or just try restore and catch error
            cmd = [
                'pg_restore',
                '-h', DB_CONFIG['host'],
                '-p', str(DB_CONFIG['port']),
                '-U', DB_CONFIG['user'],
                '-d', target_db,
                '--clean', # Clean existing objects
                '--if-exists',
                path
            ]
            
        env = os.environ.copy()
        if DB_CONFIG['password']:
            env['PGPASSWORD'] = DB_CONFIG['password']
            
        try:
            # Run restore
            subprocess.run(cmd, env=env, check=True, capture_output=True)
            self.logger.info("Base backup restored successfully")
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode()
            self.logger.error(f"Restore failed: {err}")
            
            if "too short" in err or "valid archive" in err:
                 raise RuntimeError(f"Restore failed: Backup file appears corrupted or invalid format. ({err.strip()})")
            
            raise RuntimeError(f"Restore tool failed: {err}")
    
    def restore_to_lsn(
        self,
        target_lsn: str,
        target_db: str = None,
        tables: List[str] = None,
        dry_run: bool = False
    ) -> dict:
        """
        Restore database to a specific LSN
        
        Args:
            target_lsn: Target LSN
            target_db: Target database name
            tables: List of specific tables to restore
            dry_run: If True, only simulate the restore
        
        Returns:
            Dictionary with restore results
        """
        self.logger.info(f"Starting PITR restore to LSN {target_lsn}")
        
        # Find the transaction that includes this LSN
        recovery_points = self.transaction_manager.get_consistent_recovery_points()
        
        target_point = None
        for point in recovery_points:
            if point['lsn'] == target_lsn:
                target_point = point
                break
        
        if not target_point:
            return {
                'success': False,
                'error': f"No recovery point found for LSN {target_lsn}"
            }
        
        # Convert to timestamp-based restore
        target_timestamp = datetime.fromisoformat(target_point['timestamp'])
        
        return self.restore_to_timestamp(
            target_timestamp,
            target_db,
            tables,
            dry_run
        )
    
    def _collect_changes_for_restore(
        self,
        recovery_point: dict,
        tables: List[str] = None
    ) -> List[dict]:
        """
        Collect all changes needed for restore up to recovery point
        
        Args:
            recovery_point: Recovery point metadata
            tables: Optional list of tables to filter
        
        Returns:
            List of changes to apply
        """
        target_time = datetime.fromisoformat(recovery_point['timestamp'])
        
        # Get all backups up to recovery point
        backups = self.backup_manager.list_backups_in_range(end_time=target_time)
        
        all_changes = []
        
        for backup in backups:
            try:
                changes = self.backup_manager.get_changes_from_backup(backup['backup_id'])
                
                for change in changes:
                    # Filter by timestamp
                    change_time = datetime.fromisoformat(change['timestamp'])
                    if change_time > target_time:
                        continue
                    
                    # Filter by table if specified
                    if tables and change['table'] not in tables:
                        continue
                    
                    # Only include committed transactions
                    if change['txid'] not in recovery_point.get('txid', [recovery_point['txid']]):
                        # Check if transaction was committed before recovery point
                        tx_info = self.transaction_manager.get_transaction_info(change['txid'])
                        if not tx_info or tx_info['status'] != 'COMMITTED':
                            continue
                        
                        tx_time = datetime.fromisoformat(tx_info['end_timestamp'])
                        if tx_time > target_time:
                            continue
                    
                    all_changes.append(change)
            
            except Exception as e:
                self.logger.error(f"Error reading backup {backup['backup_id']}: {e}")
        
        # Sort by LSN to ensure correct order
        all_changes.sort(key=lambda x: x['lsn'])
        
        return all_changes
    
    def _apply_changes(
        self,
        changes: List[dict],
        target_db: str,
        tables: List[str] = None
    ) -> int:
        """
        Apply changes to target database
        
        Args:
            changes: List of changes to apply
            target_db: Target database name
            tables: Optional list of tables to filter
        
        Returns:
            Number of changes applied
        """
        # Group changes by table for efficient processing
        changes_by_table = defaultdict(list)
        for change in changes:
            if tables and change['table'] not in tables:
                continue
            changes_by_table[change['table']].append(change)
        
        # Connect to target database
        conn_params = DB_CONFIG.copy()
        conn_params['dbname'] = target_db
        
        conn = psycopg2.connect(**conn_params)
        conn.autocommit = False
        
        applied_count = 0
        
        try:
            cursor = conn.cursor()
            
            for table_name, table_changes in changes_by_table.items():
                self.logger.info(f"Applying {len(table_changes)} changes to {table_name}")
                
                for change in table_changes:
                    try:
                        # If the change already has the SQL generated (SQL format backup)
                        if 'sql' in change:
                            cursor.execute(change['sql'])
                        else:
                            # Fallback to manual generation for JSON/JSONL formats
                            if change['operation'] == 'INSERT':
                                self._apply_insert(cursor, table_name, change['data'])
                            elif change['operation'] == 'UPDATE':
                                self._apply_update(cursor, table_name, change['data'], change.get('old_data'))
                            elif change['operation'] == 'DELETE':
                                self._apply_delete(cursor, table_name, change.get('old_data') or change['data'])
                        
                        applied_count += 1
                    
                    except Exception as e:
                        self.logger.error(
                            f"Error applying change to {table_name}: {e}\n"
                            f"Change: {change}"
                        )
                        # Continue with other changes
            
            conn.commit()
            self.logger.info(f"Committed {applied_count} changes")
        
        except Exception as e:
            conn.rollback()
            self.logger.error(f"Error during restore, rolling back: {e}")
            raise
        
        finally:
            conn.close()
        
        return applied_count
    
    def _apply_insert(self, cursor, table_name: str, data: dict):
        """Apply INSERT operation"""
        columns = list(data.keys())
        values = [data[col] for col in columns]
        
        placeholders = ', '.join(['%s'] * len(columns))
        columns_str = ', '.join(columns)
        
        query = f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})"
        cursor.execute(query, values)
    
    def _apply_update(self, cursor, table_name: str, new_data: dict, old_data: dict = None):
        """Apply UPDATE operation"""
        # Assume first column is primary key (this should be configurable)
        pk_column = list(new_data.keys())[0]
        pk_value = new_data[pk_column]
        
        set_clauses = []
        values = []
        
        for col, val in new_data.items():
            if col != pk_column:
                set_clauses.append(f"{col} = %s")
                values.append(val)
        
        values.append(pk_value)
        
        query = f"UPDATE {table_name} SET {', '.join(set_clauses)} WHERE {pk_column} = %s"
        cursor.execute(query, values)
    
    def _apply_delete(self, cursor, table_name: str, data: dict):
        """Apply DELETE operation"""
        # Assume first column is primary key
        pk_column = list(data.keys())[0]
        pk_value = data[pk_column]
        
        query = f"DELETE FROM {table_name} WHERE {pk_column} = %s"
        cursor.execute(query, [pk_value])
    
    def list_available_restore_points(
        self,
        start_time: datetime = None,
        end_time: datetime = None
    ) -> List[dict]:
        """
        List all available restore points
        
        Args:
            start_time: Start of time range
            end_time: End of time range
        
        Returns:
            List of restore points with metadata
        """
        recovery_points = self.transaction_manager.get_consistent_recovery_points(
            start_time, end_time
        )
        
        # Enhance with backup information
        for point in recovery_points:
            point_time = datetime.fromisoformat(point['timestamp'])
            backups = self.backup_manager.list_backups_in_range(end_time=point_time)
            point['backups_available'] = len(backups)
        
        return recovery_points

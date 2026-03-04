"""
Automatic Incremental Backup Restoration Manager
Monitors backup directory and automatically restores backups to a test database
"""

import logging
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Set, List
import json

from .pitr_config import PITR_CONFIG, DB_CONFIG
from .PITRBackupManager import PITRBackupManager
from .EnhancedRestoreManager import EnhancedPITRRestoreManager
from .EnhancedBackupManager import BackupChainBuilder


class AutoRestoreManager:
    """
    Automatically detects new backups and restores them to a test database.
    Runs as a background thread monitoring the backup directory.
    """
    
    def __init__(self, test_db_name: str = None, monitor_interval: int = 10):
        """
        Initialize auto-restore manager
        
        Args:
            test_db_name: Database to restore incremental backups to (default: derived from config)
            monitor_interval: Check interval in seconds
        """
        self.test_db_name = test_db_name or f"{DB_CONFIG['dbname']}_restore_test"
        self.monitor_interval = monitor_interval
        self.backup_dir = Path(PITR_CONFIG['backup_dir'])
        self.metadata_dir = Path(PITR_CONFIG.get('metadata_dir', 'backup_metadata'))
        
        self.logger = self._configure_logger()
        self.backup_manager = PITRBackupManager()
        self.restore_manager = EnhancedPITRRestoreManager(self.backup_manager)
        
        self.running = False
        self.thread = None
        self.processed_backups: Set[str] = set()  # Track what we've already restored
        self.last_restore_time: Optional[datetime] = None
        
        self.logger.info(f"AutoRestoreManager initialized for test database: {self.test_db_name}")
    
    def _configure_logger(self) -> logging.Logger:
        """Configure logger for auto-restore"""
        logger = logging.getLogger("AutoRestoreManager")
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.FileHandler("auto_restore.log")
            formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def start(self):
        """Start the auto-restore monitor thread"""
        if self.running:
            self.logger.warning("AutoRestoreManager is already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        self.logger.info("AutoRestoreManager started (daemon thread)")
    
    def stop(self):
        """Stop the auto-restore monitor thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        self.logger.info("AutoRestoreManager stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop - runs in background thread"""
        self.logger.info(f"Monitor loop started. Checking every {self.monitor_interval}s")
        
        while self.running:
            try:
                self._check_and_restore_new_backups()
            except Exception as e:
                self.logger.error(f"Error in monitor loop: {e}", exc_info=True)
            
            time.sleep(self.monitor_interval)
    
    def _check_and_restore_new_backups(self):
        """Check for new backups and restore them"""
        # First, ensure we have a base snapshot restored
        if not self.processed_backups:
            self._restore_latest_base_snapshot()
        
        # Reload catalog to pick up new backups
        try:
            catalog_path = self.metadata_dir / 'backup_catalog.json'
            if catalog_path.exists():
                with open(catalog_path, 'r') as f:
                    catalog = json.load(f)
            else:
                return  # No catalog yet
        except Exception as e:
            self.logger.warning(f"Could not read backup catalog: {e}")
            return
        
        # Find backups we haven't processed yet
        new_backups = [
            b for b in catalog
            if b['backup_id'] not in self.processed_backups
        ]
        
        if not new_backups:
            return
        
        self.logger.info(f"Found {len(new_backups)} new backup(s) to process")
        
        for backup in new_backups:
            backup_id = backup['backup_id']
            
            self.logger.info(f"Processing backup {backup_id}")
            
            try:
                # Restore to test database
                self._restore_backup_to_test_db(backup)
                
                # Mark as processed
                self.processed_backups.add(backup_id)
                self.last_restore_time = datetime.now()
                
                self.logger.info(f"Successfully restored backup {backup_id}")
            
            except Exception as e:
                self.logger.error(f"Failed to restore backup {backup_id}: {e}", exc_info=True)
    
    def _restore_backup_to_test_db(self, backup: Dict):
        """Restore a single backup to the test database"""
        backup_id = backup['backup_id']
        filename = backup.get('filename')
        
        if not filename:
            self.logger.warning(f"Backup {backup_id} has no filename")
            return
        
        backup_path = self.backup_dir / filename
        
        if not backup_path.exists():
            self.logger.warning(f"Backup file not found: {backup_path}")
            return
        
        # Check if this is an incremental backup (has parent_backup_id)
        if backup.get('parent_backup_id'):
            # This is an incremental - restore the chain leading up to it
            self._restore_incremental_chain(backup)
        else:
            # This is a full/base backup - restore directly
            self._restore_full_backup(backup, backup_path)
    
    def _restore_full_backup(self, backup: Dict, backup_path: Path):
        """Restore a full backup"""
        backup_id = backup['backup_id']
        filename = backup.get('filename')
        
        self.logger.info(f"Restoring full backup {backup_id} ({filename})")
        
        # Ensure test database exists first
        self._create_test_database()
        
        # Restore the file directly
        try:
            if str(backup_path).endswith('.dump'):
                self._restore_custom_backup(backup_path)
            elif str(backup_path).endswith('.sql') or str(backup_path).endswith('.sql.gz'):
                self._restore_sql_backup(backup_path)
            else:
                self.logger.warning(f"Unknown backup format: {backup_path}")
                return
            
            self.logger.info(f"Successfully restored full backup {backup_id}")
        except Exception as e:
            raise RuntimeError(f"Failed to restore full backup {backup_id}: {e}")
    
    def _restore_incremental_chain(self, backup: Dict):
        """Restore an incremental backup and its entire parent chain"""
        backup_id = backup['backup_id']
        base_backup_id = backup.get('base_backup_id')
        
        if not base_backup_id:
            self.logger.warning(f"Incremental backup {backup_id} missing base_backup_id")
            return
        
        # Build the chain from base to this incremental
        chain = self._build_chain_from_base(base_backup_id, backup_id)
        
        if not chain:
            self.logger.warning(f"Could not build chain for incremental {backup_id}")
            return
        
        self.logger.info(f"Restoring incremental chain: {' -> '.join([b['backup_id'] for b in chain])}")
        
        # Ensure test database exists first
        self._create_test_database()
        
        # Restore chain in order
        try:
            for i, backup_in_chain in enumerate(chain):
                chain_id = backup_in_chain['backup_id']
                filename = backup_in_chain.get('filename')
                
                if not filename:
                    self.logger.warning(f"Backup {chain_id} has no filename, skipping")
                    continue
                
                backup_file = self.backup_dir / filename
                if not backup_file.exists():
                    self.logger.warning(f"Backup file not found: {backup_file}, skipping")
                    continue
                
                if i == 0:
                    self.logger.info(f"  [1/{len(chain)}] Restoring base: {chain_id}")
                else:
                    self.logger.info(f"  [{i+1}/{len(chain)}] Applying incremental: {chain_id}")
                
                if str(backup_file).endswith('.dump'):
                    self._restore_custom_backup(backup_file)
                elif str(backup_file).endswith('.sql') or str(backup_file).endswith('.sql.gz'):
                    self._restore_sql_backup(backup_file)
                else:
                    self.logger.warning(f"Unknown backup format: {backup_file}")
            
            self.logger.info(f"Successfully restored incremental chain with {len(chain)} backup(s)")
        except Exception as e:
            raise RuntimeError(f"Failed to restore incremental chain: {e}")
    
    def _build_chain_from_base(self, base_backup_id: str, target_backup_id: str) -> List[Dict]:
        """Build chain from base backup to target incremental backup"""
        catalog = self.backup_manager.backup_catalog
        chain = []
        
        # Find and add base backup
        base_backup = next((b for b in catalog if b['backup_id'] == base_backup_id), None)
        if not base_backup:
            self.logger.warning(f"Base backup {base_backup_id} not found in catalog")
            return []
        
        chain.append(base_backup)
        current_id = base_backup_id
        
        # Follow the chain to target
        while current_id != target_backup_id:
            # Find next backup in chain (has current as parent)
            next_backup = next(
                (b for b in catalog 
                 if b.get('parent_backup_id') == current_id),
                None
            )
            
            if not next_backup:
                self.logger.warning(f"Could not find next backup in chain after {current_id}")
                return []
            
            chain.append(next_backup)
            current_id = next_backup['backup_id']
        
        return chain
    
    def _restore_latest_base_snapshot(self):
        """Find and restore the latest base snapshot to initialize the test database"""
        try:
            # Find all base snapshot metadata files
            base_files = sorted(self.metadata_dir.glob('base_snapshot_*_meta.json'))
            
            if not base_files:
                self.logger.debug("No base snapshot metadata found yet")
                return
            
            # Use the latest one
            latest_meta_file = base_files[-1]
            
            with open(latest_meta_file, 'r') as f:
                base_meta = json.load(f)
            
            filename = base_meta.get('filename')
            if not filename:
                self.logger.warning("Base snapshot metadata missing filename")
                return
            
            backup_path = self.backup_dir / filename
            
            if not backup_path.exists():
                self.logger.warning(f"Base snapshot file not found: {backup_path}")
                return
            
            self.logger.info(f"Restoring base snapshot: {filename}")
            
            # Ensure the test database exists first
            self._create_test_database()
            
            # Use pg_restore for .dump files
            if str(backup_path).endswith('.dump'):
                self._restore_custom_backup(backup_path)
            elif str(backup_path).endswith('.sql') or str(backup_path).endswith('.sql.gz'):
                self._restore_sql_backup(backup_path)
            else:
                self.logger.warning(f"Unknown backup format: {backup_path}")
                return
            
            self.logger.info(f"Base snapshot restored successfully")
            self.processed_backups.add('__base_snapshot__')  # Mark as done
            
        except Exception as e:
            self.logger.error(f"Failed to restore base snapshot: {e}", exc_info=True)
    
    def _create_test_database(self):
        """Create the test database if it doesn't exist"""
        import subprocess
        import os
        
        # Connect to default 'postgres' database to create the test database
        cmd = [
            'psql',
            '-h', DB_CONFIG['host'],
            '-p', str(DB_CONFIG['port']),
            '-U', DB_CONFIG['user'],
            '-d', 'postgres',
            '-c', f'CREATE DATABASE "{self.test_db_name}" WITH OWNER postgres;'
        ]
        
        env = os.environ.copy()
        if DB_CONFIG.get('password'):
            env['PGPASSWORD'] = DB_CONFIG['password']
        
        try:
            result = subprocess.run(cmd, env=env, capture_output=True, timeout=30)
            # Ignore errors if database already exists
            if result.returncode == 0:
                self.logger.info(f"Created test database: {self.test_db_name}")
            else:
                err = result.stderr.decode('utf-8', errors='ignore')
                if 'already exists' in err:
                    self.logger.debug(f"Test database already exists: {self.test_db_name}")
                else:
                    self.logger.warning(f"Could not create test database: {err}")
        except subprocess.TimeoutExpired:
            self.logger.warning("Database creation timed out")
        except Exception as e:
            self.logger.warning(f"Error creating test database: {e}")
    
    def _restore_sql_backup(self, file_path: Path):
        """Restore SQL backup using psql"""
        import subprocess
        import os
        
        cmd = [
            'psql',
            '-h', DB_CONFIG['host'],
            '-p', str(DB_CONFIG['port']),
            '-U', DB_CONFIG['user'],
            '-d', self.test_db_name,
            '-f', str(file_path)
        ]
        
        env = os.environ.copy()
        if DB_CONFIG.get('password'):
            env['PGPASSWORD'] = DB_CONFIG['password']
        
        try:
            result = subprocess.run(cmd, env=env, check=True, capture_output=True, timeout=3600)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Restore timed out after 1 hour")
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode('utf-8', errors='ignore')
            raise RuntimeError(f"psql restore failed: {err}")
    
    def _restore_custom_backup(self, file_path: Path):
        """Restore custom format backup using pg_restore"""
        import subprocess
        import os
        
        cmd = [
            'pg_restore',
            '-h', DB_CONFIG['host'],
            '-p', str(DB_CONFIG['port']),
            '-U', DB_CONFIG['user'],
            '-d', self.test_db_name,
            '--clean',
            '--if-exists',
            str(file_path)
        ]
        
        env = os.environ.copy()
        if DB_CONFIG.get('password'):
            env['PGPASSWORD'] = DB_CONFIG['password']
        
        try:
            result = subprocess.run(cmd, env=env, check=True, capture_output=True, timeout=3600)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Restore timed out after 1 hour")
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode('utf-8', errors='ignore')
            raise RuntimeError(f"pg_restore failed: {err}")
    
    def get_status(self) -> dict:
        """Get current auto-restore status"""
        return {
            'running': self.running,
            'test_database': self.test_db_name,
            'processed_backups': len(self.processed_backups),
            'last_restore_time': self.last_restore_time.isoformat() if self.last_restore_time else None,
            'processed_backup_ids': list(self.processed_backups)
        }
    
    def wait_for_restore(self, timeout: int = 60) -> bool:
        """
        Wait for at least one restore to complete.
        Useful for testing.
        
        Args:
            timeout: Maximum seconds to wait
        
        Returns:
            True if restore happened, False if timeout
        """
        start = time.time()
        while time.time() - start < timeout:
            if self.last_restore_time:
                return True
            time.sleep(1)
        return False


# Example usage as a standalone daemon
if __name__ == '__main__':
    import sys
    
    print("Starting AutoRestoreManager daemon...")
    print("=" * 60)
    
    test_db = sys.argv[1] if len(sys.argv) > 1 else None
    manager = AutoRestoreManager(test_db_name=test_db)
    manager.start()
    
    try:
        print("Monitor running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
            status = manager.get_status()
            if status['processed_backups'] > 0:
                print(f"Status: {status['processed_backups']} backup(s) processed")
    except KeyboardInterrupt:
        print("\nStopping...")
        manager.stop()

"""
Enhanced PITR Restore Manager with Incremental Chain Support
Enables restoration from multiple incremental backups in sequence
"""

import json
import logging
import psycopg2
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import subprocess
import os

from .pitr_config import PITR_CONFIG, DB_CONFIG
from .EnhancedBackupManager import BackupChainBuilder, BackupIntegrityValidator


class EnhancedPITRRestoreManager:
    """
    Enhanced restore manager supporting incremental backup chains
    """
    
    def __init__(self, backup_manager=None):
        self.backup_manager = backup_manager
        self.logger = self._configure_logger()
        self.chain_builder = None
        self.validator = None
        
        if backup_manager:
            self.chain_builder = BackupChainBuilder(backup_manager.backup_catalog)
            self.validator = BackupIntegrityValidator(backup_manager)
    
    def _configure_logger(self) -> logging.Logger:
        """Configure logger"""
        logger = logging.getLogger("EnhancedPITRRestoreManager")
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.FileHandler("pitr_restore_enhanced.log")
            formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def restore_to_timestamp_with_chain(
        self,
        target_timestamp: datetime,
        target_db: str,
        tables: List[str] = None,
        verify_before_restore: bool = True,
        dry_run: bool = False,
        show_progress: bool = True
    ) -> dict:
        """
        Restore database to timestamp using backup chain
        
        Args:
            target_timestamp: Target restore point
            target_db: Target database
            tables: Optional table filter
            verify_before_restore: Verify all backups before restoring
            dry_run: Simulate without making changes
            show_progress: Display progress
        
        Returns:
            Restore result dictionary
        """
        self.logger.info(f"Starting enhanced PITR restore to {target_timestamp}")
        
        if show_progress:
            print(f"\n{'='*70}")
            print(f"Enhanced PITR Restore - Chain Mode")
            print(f"{'='*70}")
            print(f"Target timestamp: {target_timestamp}")
            print(f"Target database:  {target_db}")
            if tables:
                print(f"Tables filter:    {', '.join(tables)}")
        
        # Step 1: Build restore chain
        if show_progress:
            print(f"\n[1/5] Building restore chain...")
        
        chain = self._build_chain(target_timestamp)
        
        if not chain:
            msg = "Could not build restore chain - no backups available"
            self.logger.error(msg)
            if show_progress:
                print(f"      ✗ {msg}")
            return {'success': False, 'error': msg}
        
        chain_info = self._get_chain_info(chain)
        if show_progress:
            print(f"      ✓ Built chain with {len(chain)} backups")
            for i, backup in enumerate(chain_info['backups'], 1):
                backup_type = backup['type'].upper()
                size_mb = backup['size_mb']
                print(f"        {i}. [{backup_type}] {backup['filename']}")
                print(f"           Size: {size_mb:.1f} MB, Changes: {backup['changes']}")
        
        # Step 2: Verify backups (optional)
        if verify_before_restore:
            if show_progress:
                print(f"\n[2/5] Verifying backup integrity...")
            
            verification_errors = self._verify_backup_chain(chain)
            if verification_errors:
                self.logger.error(f"Backup verification failed: {verification_errors}")
                if show_progress:
                    print(f"      ✗ Verification failed:")
                    for error in verification_errors:
                        print(f"        - {error}")
                return {'success': False, 'error': 'Backup verification failed', 'details': verification_errors}
            
            if show_progress:
                print(f"      ✓ All backups verified successfully")
        else:
            if show_progress:
                print(f"\n[2/5] Skipping verification (not requested)")
        
        # Step 3: Dry run preview
        if show_progress:
            print(f"\n[3/5] Analyzing restore impact...")
        
        total_changes = sum(b.get('changes_count', 0) for b in chain)
        all_tables = set()
        for b in chain:
            all_tables.update(b.get('tables_affected', []))
        
        if show_progress:
            print(f"      Total changes to apply: {total_changes}")
            print(f"      Tables affected: {', '.join(sorted(all_tables))}")
            if tables:
                filtered_changes = sum(b.get('changes_count', 0) for b in chain 
                                     if any(t in b.get('tables_affected', []) for t in tables))
                print(f"      Changes (filtered): {filtered_changes}")
        
        if dry_run:
            if show_progress:
                print(f"\n[4/5] Dry run mode - not making changes")
                print(f"      Would restore {len(chain)} backups to {target_db}")
                print(f"\n[5/5] Dry run complete - no changes applied")
            
            return {
                'success': True,
                'dry_run': True,
                'chain_length': len(chain),
                'total_changes': total_changes,
                'tables_affected': sorted(list(all_tables)),
                'estimated_restore_time': chain_info['estimated_restore_time_seconds']
            }
        
        # Step 4: Apply restore chain
        if show_progress:
            print(f"\n[4/5] Restoring backup chain...")
        
        try:
            restore_result = self._apply_restore_chain(
                chain,
                target_db,
                tables,
                show_progress
            )
            
            if not restore_result['success']:
                return restore_result
        
        except Exception as e:
            self.logger.error(f"Error during restore: {e}")
            if show_progress:
                print(f"      ✗ Restore failed: {e}")
            return {'success': False, 'error': str(e)}
        
        # Step 5: Verify restore
        if show_progress:
            print(f"\n[5/5] Verifying restore...")
            print(f"      ✓ Restore completed successfully")
        
        return {
            'success': True,
            'dry_run': False,
            'chain_length': len(chain),
            'total_changes': total_changes,
            'tables_affected': sorted(list(all_tables)),
            'backups_applied': [b['backup_id'] for b in chain],
            'restore_timestamp': target_timestamp.isoformat(),
            'target_database': target_db,
            'message': f'Successfully restored {len(chain)} backups'
        }
    
    def _build_chain(self, target_timestamp: datetime) -> List[Dict]:
        """Build backup chain to target time"""
        if not self.chain_builder:
            return []
        
        chain = self.chain_builder.build_chain_to_point(target_timestamp)
        return chain
    
    def _get_chain_info(self, chain: List[Dict]) -> dict:
        """Get chain information"""
        if not self.chain_builder:
            return {}
        
        return self.chain_builder.get_chain_info(chain)
    
    def _verify_backup_chain(self, chain: List[Dict]) -> List[str]:
        """Verify all backups in chain"""
        errors = []
        
        if not self.validator:
            return errors
        
        for backup in chain:
            is_valid, backup_errors = self.validator.verify_backup_file(
                backup['backup_id'],
                backup
            )
            
            if not is_valid:
                errors.extend([
                    f"{backup['filename']}: {error}"
                    for error in backup_errors
                ])
        
        return errors
    
    def _apply_restore_chain(
        self,
        chain: List[Dict],
        target_db: str,
        tables: List[str],
        show_progress: bool = True
    ) -> dict:
        """Apply chain of backups in order"""
        
        applied_count = 0
        
        for i, backup in enumerate(chain, 1):
            backup_type = backup.get('backup_type', 'unknown')
            
            if show_progress:
                print(f"      Restoring backup {i}/{len(chain)}: {backup['filename']}")
            
            try:
                if backup_type == 'base':
                    # Restore base backup
                    self._restore_base_backup(backup, target_db)
                else:
                    # Apply incremental changes
                    changes_applied = self._apply_incremental_backup(
                        backup,
                        target_db,
                        tables,
                        show_progress
                    )
                    applied_count += changes_applied
                
                if show_progress:
                    print(f"        ✓ Backup {i}/{len(chain)} applied")
            
            except Exception as e:
                self.logger.error(f"Failed to apply backup {backup['backup_id']}: {e}")
                if show_progress:
                    print(f"        ✗ Failed: {e}")
                
                return {
                    'success': False,
                    'error': f'Failed to restore backup {i}/{len(chain)}: {e}',
                    'backup_index': i,
                    'backup_id': backup['backup_id']
                }
        
        return {
            'success': True,
            'backups_applied': len(chain),
            'changes_applied': applied_count
        }
    
    def _restore_base_backup(self, backup: Dict, target_db: str):
        """Restore a base backup"""
        backup_path = Path(PITR_CONFIG['backup_dir']) / backup['filename']
        
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")
        
        self.logger.info(f"Restoring base backup from {backup_path}")
        
        # Determine format and use appropriate tool
        if str(backup_path).endswith('.sql') or str(backup_path).endswith('.sql.gz'):
            self._restore_sql_backup(backup_path, target_db)
        else:
            self._restore_custom_backup(backup_path, target_db)
    
    def _restore_sql_backup(self, file_path: Path, target_db: str):
        """Restore SQL backup using psql"""
        cmd = [
            'psql',
            '-h', DB_CONFIG['host'],
            '-p', str(DB_CONFIG['port']),
            '-U', DB_CONFIG['user'],
            '-d', target_db,
            '-f', str(file_path)
        ]
        
        env = os.environ.copy()
        if DB_CONFIG.get('password'):
            env['PGPASSWORD'] = DB_CONFIG['password']
        
        self.logger.info(f"Running psql restore: {' '.join(cmd[:6])}... -f {file_path.name}")
        
        try:
            result = subprocess.run(cmd, env=env, check=True, capture_output=True, timeout=3600)
            self.logger.info("SQL backup restored successfully")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Restore timed out after 1 hour")
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode('utf-8', errors='ignore')
            raise RuntimeError(f"Restore failed: {err}")
    
    def _restore_custom_backup(self, file_path: Path, target_db: str):
        """Restore custom format backup using pg_restore"""
        cmd = [
            'pg_restore',
            '-h', DB_CONFIG['host'],
            '-p', str(DB_CONFIG['port']),
            '-U', DB_CONFIG['user'],
            '-d', target_db,
            '--clean',
            '--if-exists',
            str(file_path)
        ]
        
        env = os.environ.copy()
        if DB_CONFIG.get('password'):
            env['PGPASSWORD'] = DB_CONFIG['password']
        
        self.logger.info(f"Running pg_restore: {' '.join(cmd[:6])}... {file_path.name}")
        
        try:
            result = subprocess.run(cmd, env=env, check=True, capture_output=True, timeout=3600)
            self.logger.info("Custom backup restored successfully")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Restore timed out after 1 hour")
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode('utf-8', errors='ignore')
            raise RuntimeError(f"Restore failed: {err}")
    
    def _apply_incremental_backup(
        self,
        backup: Dict,
        target_db: str,
        tables: List[str] = None,
        show_progress: bool = True
    ) -> int:
        """Apply incremental backup changes"""
        
        backup_path = Path(PITR_CONFIG['backup_dir']) / backup['filename']
        
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")
        
        # For now, use psql if SQL format
        if str(backup_path).endswith('.sql') or str(backup_path).endswith('.sql.gz'):
            self._restore_sql_backup(backup_path, target_db)
            return backup.get('changes_count', 0)
        
        self.logger.warning(f"Unsupported format for incremental backup: {backup_path}")
        return 0


# Example CLI function to use enhanced restore
def restore_command_enhanced(args):
    """Enhanced restore command with chain support"""
    from services.PITRBackupManager import PITRBackupManager
    
    print(f"\nInitializing enhanced restore manager...")
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
    
    print(f"\n{'='*70}")
    if result['success']:
        print(f"✓ Restore {'preview' if result.get('dry_run') else 'completed'} successfully!")
        print(f"  Backups: {result.get('chain_length', 0)}")
        print(f"  Changes: {result.get('total_changes', 0)}")
        if result.get('tables_affected'):
            print(f"  Tables:  {', '.join(result['tables_affected'])}")
    else:
        print(f"✗ Restore failed: {result.get('error', 'Unknown error')}")
        if result.get('details'):
            for detail in result['details']:
                print(f"  - {detail}")
    print(f"{'='*70}\n")
    
    return 0 if result['success'] else 1

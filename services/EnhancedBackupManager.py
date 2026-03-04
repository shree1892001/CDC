"""
Enhanced Backup Manager with Lineage Tracking and Chain Restoration
Implements incremental backup chains for restorable incremental backups
"""

import json
import gzip
import logging
import os
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import threading
from collections import defaultdict
import psycopg2.extensions

from .pitr_config import PITR_CONFIG, DB_CONFIG
from .TransactionLogManager import TransactionLogManager


class EnhancedBackupMetadata:
    """
    Enhanced metadata tracking for incremental backup lineage
    """
    
    def __init__(self):
        self.backup_id: str = None
        self.filename: str = None
        self.backup_type: str = "incremental"  # "base" or "incremental"
        
        # Lineage tracking
        self.parent_backup_id: Optional[str] = None  # Direct parent
        self.base_backup_id: str = None  # Root base backup
        self.chain_depth: int = 0  # 0 = base, 1+ = incremental
        self.sequence_number: int = 0  # Order in chain
        
        # Coverage
        self.covers_entire_db: bool = False  # Can restore independently?
        self.full_coverage: bool = False  # Has all data to restore?
        
        # Standard fields
        self.start_time: str = None
        self.end_time: str = None
        self.start_lsn: str = None
        self.end_lsn: str = None
        self.changes_count: int = 0
        self.tables_affected: List[str] = []
        self.transactions: List[int] = []
        
        # Quality assurance
        self.format: str = PITR_CONFIG.get('backup_format', 'sql')
        self.compressed: bool = PITR_CONFIG.get('compression_enabled', False)
        self.checksums: Dict[str, str] = {}  # sha256, md5, etc.
        self.size_bytes: int = 0
        self.verified: bool = False
        self.verified_at: Optional[str] = None
        self.verification_errors: List[str] = []
    
    def to_dict(self) -> dict:
        """Convert metadata to dictionary"""
        return {
            'backup_id': self.backup_id,
            'filename': self.filename,
            'backup_type': self.backup_type,
            'parent_backup_id': self.parent_backup_id,
            'base_backup_id': self.base_backup_id,
            'chain_depth': self.chain_depth,
            'sequence_number': self.sequence_number,
            'covers_entire_db': self.covers_entire_db,
            'full_coverage': self.full_coverage,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'start_lsn': self.start_lsn,
            'end_lsn': self.end_lsn,
            'changes_count': self.changes_count,
            'tables_affected': self.tables_affected,
            'transactions': self.transactions,
            'format': self.format,
            'compressed': self.compressed,
            'checksums': self.checksums,
            'size_bytes': self.size_bytes,
            'verified': self.verified,
            'verified_at': self.verified_at,
            'verification_errors': self.verification_errors
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'EnhancedBackupMetadata':
        """Create metadata from dictionary"""
        meta = cls()
        for key, value in data.items():
            if hasattr(meta, key):
                setattr(meta, key, value)
        return meta


class BackupChainBuilder:
    """
    Builds restore chains from incremental backups
    """
    
    def __init__(self, catalog: List[Dict]):
        """
        Initialize with backup catalog
        
        Args:
            catalog: List of backup metadata dictionaries
        """
        self.catalog = catalog
        self.backup_map = {b['backup_id']: b for b in catalog}
        self.logger = logging.getLogger("BackupChainBuilder")
    
    def build_chain_to_point(
        self,
        target_time: datetime,
        target_lsn: Optional[str] = None
    ) -> List[Dict]:
        """
        Build a restore chain to a target point in time or LSN
        
        Args:
            target_time: Target restore time
            target_lsn: Optional target LSN (if more precise than time)
        
        Returns:
            Ordered list of backups to restore
        """
        # Find base backup before target
        base_backup = self._find_base_backup(target_time)
        
        if not base_backup:
            self.logger.error("No base backup found before target time")
            return []
        
        # Build chain of incrementals after base
        chain = [base_backup]
        current_end_time = datetime.fromisoformat(base_backup['end_time'])
        
        while current_end_time < target_time:
            # Find next incremental after current point
            next_backup = self._find_next_incremental(
                current_end_time,
                base_backup['backup_id']
            )
            
            if not next_backup:
                break
            
            chain.append(next_backup)
            current_end_time = datetime.fromisoformat(next_backup['end_time'])
        
        return chain
    
    def _find_base_backup(self, before_time: datetime) -> Optional[Dict]:
        """Find latest base backup before time"""
        candidates = [
            b for b in self.catalog
            if (b.get('backup_type') == 'base' or b.get('parent_backup_id') is None) and
            datetime.fromisoformat(b['end_time']) < before_time
        ]
        
        if not candidates:
            return None
        
        # Return most recent base backup
        return max(candidates, key=lambda b: datetime.fromisoformat(b['end_time']))
    
    def _find_next_incremental(
        self,
        after_time: datetime,
        base_backup_id: str
    ) -> Optional[Dict]:
        """Find next incremental backup after time in same chain"""
        candidates = [
            b for b in self.catalog
            if (b.get('backup_type') == 'incremental' or b.get('parent_backup_id') is not None) and
            b.get('base_backup_id') == base_backup_id and
            datetime.fromisoformat(b['start_time']) >= after_time
        ]
        
        if not candidates:
            return None
        
        # Return earliest next incremental
        return min(candidates, key=lambda b: datetime.fromisoformat(b['start_time']))
    
    def get_chain_info(self, chain: List[Dict]) -> dict:
        """Get information about a backup chain"""
        if not chain:
            return {'valid': False, 'error': 'Empty chain'}
        
        total_changes = sum(b.get('changes_count', 0) for b in chain)
        total_size = sum(b.get('size_bytes', 0) for b in chain)
        tables = set()
        
        for backup in chain:
            tables.update(backup.get('tables_affected', []))
        
        return {
            'valid': True,
            'chain_length': len(chain),
            'backups': [
                {
                    'id': b['backup_id'],
                    'filename': b['filename'],
                    'type': b.get('backup_type', 'unknown'),
                    'changes': b.get('changes_count', 0),
                    'size_mb': b.get('size_bytes', 0) / (1024 * 1024),
                    'time_range': f"{b['start_time']} → {b['end_time']}"
                }
                for b in chain
            ],
            'total_changes': total_changes,
            'total_size_mb': total_size / (1024 * 1024),
            'tables_affected': sorted(list(tables)),
            'estimated_restore_time_seconds': self._estimate_restore_time(total_changes)
        }
    
    def _estimate_restore_time(self, changes: int) -> int:
        """Estimate restore time based on change count"""
        # Rough estimate: ~100-200 changes per second on average hardware
        changes_per_sec = 150
        return max(10, int(changes / changes_per_sec))


class BackupIntegrityValidator:
    """
    Validates backup file integrity and restorable capability
    """
    
    def __init__(self, backup_manager):
        self.backup_manager = backup_manager
        self.logger = logging.getLogger("BackupIntegrityValidator")
    
    def calculate_checksums(self, file_path: Path) -> Dict[str, str]:
        """Calculate checksums for a backup file"""
        checksums = {}
        
        try:
            # SHA256
            sha256_hash = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b''):
                    sha256_hash.update(chunk)
            checksums['sha256'] = sha256_hash.hexdigest()
            
            # MD5 (for quick comparison)
            md5_hash = hashlib.md5()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b''):
                    md5_hash.update(chunk)
            checksums['md5'] = md5_hash.hexdigest()
            
            self.logger.info(f"Checksums calculated: SHA256={checksums['sha256'][:16]}...")
            
        except Exception as e:
            self.logger.error(f"Error calculating checksums: {e}")
        
        return checksums
    
    def verify_backup_file(self, backup_id: str, metadata: EnhancedBackupMetadata) -> Tuple[bool, List[str]]:
        """
        Verify backup file integrity
        
        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []
        backup_path = Path(PITR_CONFIG['backup_dir']) / metadata.filename
        
        # Check file existence
        if not backup_path.exists():
            return False, [f"Backup file not found: {backup_path}"]
        
        # Verify file not empty
        if backup_path.stat().st_size == 0:
            errors.append("Backup file is empty")
            return False, errors
        
        # Verify checksums if available
        if metadata.checksums:
            actual_checksums = self.calculate_checksums(backup_path)
            
            if actual_checksums.get('sha256') != metadata.checksums.get('sha256'):
                errors.append(
                    f"SHA256 mismatch: expected {metadata.checksums['sha256']}, "
                    f"got {actual_checksums['sha256']}"
                )
        
        # Verify file can be parsed
        try:
            self._parse_backup_sample(backup_path, metadata.format, limit=10)
        except Exception as e:
            errors.append(f"Cannot parse backup file: {e}")
            return False, errors
        
        # Verify LSN ordering
        try:
            if not self._verify_lsn_ordering(backup_path, metadata.format):
                errors.append("LSN ordering violated in backup file")
        except Exception as e:
            self.logger.warning(f"Could not verify LSN ordering: {e}")
        
        return len(errors) == 0, errors
    
    def _parse_backup_sample(self, file_path: Path, format_type: str, limit: int = 10):
        """Parse and sample backup file"""
        if format_type == 'sql':
            self._parse_sql_sample(file_path, limit)
        elif format_type in ['jsonl', 'json']:
            self._parse_json_sample(file_path, limit)
    
    def _parse_sql_sample(self, file_path: Path, limit: int):
        """Parse SQL backup sample"""
        open_func = gzip.open if file_path.suffix == '.gz' else open
        mode = 'rt' if file_path.suffix == '.gz' else 'r'
        
        count = 0
        with open_func(file_path, mode, encoding='utf-8', errors='ignore') as f:
            for line in f:
                # Skip metadata and comments
                if line.strip().startswith('--'):
                    continue
                
                # Check for SQL statements
                if any(line.strip().upper().startswith(kw) for kw in ['INSERT', 'UPDATE', 'DELETE', 'BEGIN', 'COMMIT']):
                    count += 1
                    if count >= limit:
                        break
        
        if count == 0:
            raise ValueError("No SQL statements found in backup file")
    
    def _parse_json_sample(self, file_path: Path, limit: int):
        """Parse JSON/JSONL backup sample"""
        open_func = gzip.open if file_path.suffix == '.gz' else open
        mode = 'rt' if file_path.suffix == '.gz' else 'r'
        
        count = 0
        with open_func(file_path, mode, encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    # Skip metadata
                    if '__metadata__' not in data:
                        count += 1
                        if count >= limit:
                            break
                except json.JSONDecodeError:
                    pass
        
        if count == 0:
            raise ValueError("No valid JSON records found in backup file")
    
    def _verify_lsn_ordering(self, file_path: Path, format_type: str) -> bool:
        """Verify LSN ordering in backup file"""
        lsns = []
        
        if format_type == 'sql':
            lsns = self._extract_lsns_from_sql(file_path)
        elif format_type in ['jsonl', 'json']:
            lsns = self._extract_lsns_from_json(file_path)
        
        if not lsns:
            return True  # Can't verify, assume OK
        
        # Check if sorted
        return lsns == sorted(lsns)
    
    def _extract_lsns_from_sql(self, file_path: Path) -> List[str]:
        """Extract LSNs from SQL backup file"""
        lsns = []
        open_func = gzip.open if file_path.suffix == '.gz' else open
        mode = 'rt' if file_path.suffix == '.gz' else 'r'
        
        with open_func(file_path, mode, encoding='utf-8', errors='ignore') as f:
            for line in f:
                # LSNs are in comments: -- LSN: 0/123456
                if '-- LSN:' in line:
                    try:
                        lsn = line.split('-- LSN:')[1].split(',')[0].strip()
                        lsns.append(lsn)
                    except:
                        pass
        
        return lsns
    
    def _extract_lsns_from_json(self, file_path: Path) -> List[str]:
        """Extract LSNs from JSON backup file"""
        lsns = []
        open_func = gzip.open if file_path.suffix == '.gz' else open
        mode = 'rt' if file_path.suffix == '.gz' else 'r'
        
        with open_func(file_path, mode, encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if 'lsn' in data:
                        lsns.append(data['lsn'])
                except json.JSONDecodeError:
                    pass
        
        return lsns


# Example usage in PITRBackupManager:
class EnhancedPITRBackupManager:
    """
    Extends PITRBackupManager with incremental backup chaining capability
    """
    
    def __init__(self):
        # ... existing init code ...
        self.chain_builder = BackupChainBuilder(self.backup_catalog)
        self.validator = BackupIntegrityValidator(self)
    
    def set_as_base_backup(self, backup_id: str):
        """Mark a backup as a base backup"""
        metadata = self._get_backup_metadata(backup_id)
        metadata['backup_type'] = 'base'
        metadata['chain_depth'] = 0
        metadata['base_backup_id'] = backup_id
        metadata['parent_backup_id'] = None
        self._save_metadata(backup_id, metadata)
    
    def set_as_incremental(self, backup_id: str, parent_id: str):
        """Mark a backup as incremental with parent"""
        metadata = self._get_backup_metadata(backup_id)
        parent_metadata = self._get_backup_metadata(parent_id)
        
        metadata['backup_type'] = 'incremental'
        metadata['parent_backup_id'] = parent_id
        metadata['base_backup_id'] = parent_metadata.get('base_backup_id', parent_id)
        metadata['chain_depth'] = parent_metadata.get('chain_depth', 0) + 1
        self._save_metadata(backup_id, metadata)
    
    def build_restore_chain(self, target_time: datetime) -> List[Dict]:
        """Build chain of backups for restore"""
        return self.chain_builder.build_chain_to_point(target_time)
    
    def verify_backup(self, backup_id: str) -> Tuple[bool, List[str]]:
        """Verify backup integrity"""
        metadata = self._get_backup_metadata(backup_id)
        is_valid, errors = self.validator.verify_backup_file(backup_id, metadata)
        
        # Update metadata
        metadata['verified'] = is_valid
        metadata['verified_at'] = datetime.now().isoformat()
        metadata['verification_errors'] = errors
        self._save_metadata(backup_id, metadata)
        
        return is_valid, errors

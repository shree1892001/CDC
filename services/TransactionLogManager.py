"""
Transaction Log Manager
Tracks transaction boundaries and metadata for PITR consistency
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
from collections import defaultdict
import threading

from .pitr_config import PITR_CONFIG


class TransactionLogManager:
    """
    Manages transaction metadata for ensuring PITR consistency.
    Tracks BEGIN, COMMIT, ROLLBACK events and maintains transaction state.
    """
    
    def __init__(self, log_dir: str = None):
        self.log_dir = Path(log_dir or PITR_CONFIG['transaction_log_dir'])
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger = self._configure_logger()
        
        # In-memory transaction tracking
        self.active_transactions: Dict[int, dict] = {}  # txid -> metadata
        self.completed_transactions: List[dict] = []
        self.transaction_lock = threading.Lock()
        
        # Current transaction log file
        self.current_log_file = self._get_current_log_file()
        
        # Load existing state
        self._load_state()
    
    def _configure_logger(self) -> logging.Logger:
        """Configure logger for transaction tracking"""
        logger = logging.getLogger("TransactionLogManager")
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.FileHandler(
                self.log_dir / "transaction_manager.log"
            )
            formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def _get_current_log_file(self) -> Path:
        """Get current transaction log file path"""
        date_str = datetime.now().strftime('%Y%m%d')
        return self.log_dir / f"transactions_{date_str}.jsonl"
    
    def _load_state(self):
        """Load existing transaction state from disk"""
        if self.current_log_file.exists():
            try:
                with open(self.current_log_file, 'r') as f:
                    for line in f:
                        if line.strip():
                            tx_data = json.loads(line)
                            if tx_data['status'] == 'ACTIVE':
                                self.active_transactions[tx_data['txid']] = tx_data
                            else:
                                self.completed_transactions.append(tx_data)
                
                self.logger.info(
                    f"Loaded {len(self.active_transactions)} active and "
                    f"{len(self.completed_transactions)} completed transactions"
                )
            except Exception as e:
                self.logger.error(f"Error loading transaction state: {e}")
    
    def begin_transaction(self, txid: int, lsn: str, timestamp: datetime = None):
        """
        Record the beginning of a transaction
        
        Args:
            txid: Transaction ID
            lsn: Log Sequence Number
            timestamp: Transaction start timestamp
        """
        with self.transaction_lock:
            if txid in self.active_transactions:
                self.logger.warning(f"Transaction {txid} already active, ignoring BEGIN")
                return
            
            tx_metadata = {
                'txid': txid,
                'start_lsn': lsn,
                'start_timestamp': (timestamp or datetime.now()).isoformat(),
                'status': 'ACTIVE',
                'changes_count': 0,
                'tables_affected': set()
            }
            
            self.active_transactions[txid] = tx_metadata
            self._write_transaction_log(tx_metadata)
            
            self.logger.debug(f"Transaction {txid} started at LSN {lsn}")
    
    def add_change_to_transaction(self, txid: int, table_name: str):
        """
        Record a change within a transaction
        
        Args:
            txid: Transaction ID
            table_name: Name of the affected table
        """
        with self.transaction_lock:
            if txid not in self.active_transactions:
                # Auto-create transaction if not exists (for implicit transactions)
                self.logger.warning(
                    f"Transaction {txid} not found, auto-creating"
                )
                self.begin_transaction(txid, "unknown", datetime.now())
            
            tx = self.active_transactions[txid]
            tx['changes_count'] += 1
            if isinstance(tx['tables_affected'], set):
                tx['tables_affected'].add(table_name)
            else:
                tx['tables_affected'] = {table_name}
    
    def commit_transaction(self, txid: int, lsn: str, timestamp: datetime = None):
        """
        Record transaction commit
        
        Args:
            txid: Transaction ID
            lsn: Commit LSN
            timestamp: Commit timestamp
        """
        with self.transaction_lock:
            if txid not in self.active_transactions:
                self.logger.warning(f"Transaction {txid} not found for COMMIT")
                return
            
            tx = self.active_transactions.pop(txid)
            tx['end_lsn'] = lsn
            tx['end_timestamp'] = (timestamp or datetime.now()).isoformat()
            tx['status'] = 'COMMITTED'
            tx['tables_affected'] = list(tx['tables_affected'])  # Convert set to list for JSON
            
            self.completed_transactions.append(tx)
            self._write_transaction_log(tx)
            
            self.logger.info(
                f"Transaction {txid} committed at LSN {lsn} "
                f"({tx['changes_count']} changes)"
            )
    
    def rollback_transaction(self, txid: int, lsn: str, timestamp: datetime = None):
        """
        Record transaction rollback
        
        Args:
            txid: Transaction ID
            lsn: Rollback LSN
            timestamp: Rollback timestamp
        """
        with self.transaction_lock:
            if txid not in self.active_transactions:
                self.logger.warning(f"Transaction {txid} not found for ROLLBACK")
                return
            
            tx = self.active_transactions.pop(txid)
            tx['end_lsn'] = lsn
            tx['end_timestamp'] = (timestamp or datetime.now()).isoformat()
            tx['status'] = 'ROLLED_BACK'
            tx['tables_affected'] = list(tx['tables_affected'])
            
            self.completed_transactions.append(tx)
            self._write_transaction_log(tx)
            
            self.logger.info(f"Transaction {txid} rolled back at LSN {lsn}")
    
    def _write_transaction_log(self, tx_data: dict):
        """Write transaction metadata to log file"""
        try:
            # Check if we need to rotate to a new log file
            current_file = self._get_current_log_file()
            if current_file != self.current_log_file:
                self.current_log_file = current_file
            
            with open(self.current_log_file, 'a') as f:
                # Convert sets to lists for JSON serialization
                tx_copy = tx_data.copy()
                if 'tables_affected' in tx_copy and isinstance(tx_copy['tables_affected'], set):
                    tx_copy['tables_affected'] = list(tx_copy['tables_affected'])
                
                f.write(json.dumps(tx_copy) + '\n')
        
        except Exception as e:
            self.logger.error(f"Error writing transaction log: {e}")
    
    def get_consistent_recovery_points(
        self, 
        start_time: datetime = None, 
        end_time: datetime = None
    ) -> List[dict]:
        """
        Get list of transaction-consistent recovery points
        
        Args:
            start_time: Start of time range
            end_time: End of time range
        
        Returns:
            List of committed transactions that are safe recovery points
        """
        recovery_points = []
        
        for tx in self.completed_transactions:
            if tx['status'] != 'COMMITTED':
                continue
            
            tx_time = datetime.fromisoformat(tx['end_timestamp'])
            
            if start_time and tx_time < start_time:
                continue
            if end_time and tx_time > end_time:
                continue
            
            recovery_points.append({
                'txid': tx['txid'],
                'timestamp': tx['end_timestamp'],
                'lsn': tx['end_lsn'],
                'changes_count': tx['changes_count'],
                'tables_affected': tx['tables_affected']
            })
        
        return sorted(recovery_points, key=lambda x: x['timestamp'])
    
    def get_transaction_info(self, txid: int) -> Optional[dict]:
        """Get information about a specific transaction"""
        # Check active transactions
        if txid in self.active_transactions:
            return self.active_transactions[txid].copy()
        
        # Check completed transactions
        for tx in self.completed_transactions:
            if tx['txid'] == txid:
                return tx.copy()
        
        return None
    
    def get_active_transactions(self) -> List[dict]:
        """Get list of currently active transactions"""
        with self.transaction_lock:
            return list(self.active_transactions.values())
    
    def cleanup_old_logs(self, retention_days: int = None):
        """
        Remove old transaction log files
        
        Args:
            retention_days: Number of days to retain logs
        """
        retention_days = retention_days or PITR_CONFIG['retention_days']
        cutoff_date = datetime.now().timestamp() - (retention_days * 86400)
        
        removed_count = 0
        for log_file in self.log_dir.glob("transactions_*.jsonl"):
            if log_file.stat().st_mtime < cutoff_date:
                try:
                    log_file.unlink()
                    removed_count += 1
                    self.logger.info(f"Removed old transaction log: {log_file.name}")
                except Exception as e:
                    self.logger.error(f"Error removing {log_file.name}: {e}")
        
        if removed_count > 0:
            self.logger.info(f"Cleaned up {removed_count} old transaction log files")
    
    def get_statistics(self) -> dict:
        """Get transaction statistics"""
        with self.transaction_lock:
            committed = sum(1 for tx in self.completed_transactions if tx['status'] == 'COMMITTED')
            rolled_back = sum(1 for tx in self.completed_transactions if tx['status'] == 'ROLLED_BACK')
            
            return {
                'active_transactions': len(self.active_transactions),
                'completed_transactions': len(self.completed_transactions),
                'committed_transactions': committed,
                'rolled_back_transactions': rolled_back,
                'total_changes': sum(tx['changes_count'] for tx in self.completed_transactions)
            }

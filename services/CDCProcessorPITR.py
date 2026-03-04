"""
Enhanced CDC Processor with PITR Support
Integrates logical replication with LSN-tracked backups for Point-in-Time Recovery
"""

import logging
import json
import os
import re
import signal
import sys
from datetime import datetime
from typing import Optional, Dict, Any
import psycopg2.errors
from psycopg2.extras import LogicalReplicationConnection

from utils.ApplicationConnection import ApplicationConnection
from .PITRBackupManager import PITRBackupManager
from .TransactionLogManager import TransactionLogManager
from .pitr_config import PITR_CONFIG, DB_CONFIG, REPLICATION_CONFIG


class CDCProcessor:
    """
    Enhanced CDC Processor with PITR capabilities.
    Captures changes from PostgreSQL logical replication and stores them
    with LSN tracking for point-in-time recovery.
    """
    
    def __init__(self, slot_name: str = None, output_plugin: str = None, backup_dir: str = None):
        self.slot_name = slot_name or REPLICATION_CONFIG['slot_name']
        self.output_plugin = output_plugin or REPLICATION_CONFIG['output_plugin']
        self.backup_dir = backup_dir or PITR_CONFIG['backup_dir']
        
        # Initialize logging
        self.logger = self._configure_logger()
        
        # Initialize PITR components
        self.transaction_manager = TransactionLogManager()
        self.backup_manager = PITRBackupManager(
            backup_dir=self.backup_dir,
            transaction_manager=self.transaction_manager
        )
        
        # Database connections
        self.replication_conn = None
        self.cursor = None
        self._connect_replication()
        
        # Shutdown handling
        self.shutdown_requested = False
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        
        # State tracking
        self.last_lsn = self._load_last_lsn()
        self.current_txid = None
        
        self.logger.info("CDC Processor with PITR initialized")
    
    def _configure_logger(self) -> logging.Logger:
        """Configure logger for CDC processor"""
        logger = logging.getLogger("CDC_Processor")
        logger.setLevel(getattr(logging, PITR_CONFIG['log_level']))
        
        if not logger.handlers:
            file_handler = logging.FileHandler("cdc_changes.log")
            file_handler.setLevel(logging.INFO)
            
            formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        
        return logger
    
    def _connect_replication(self):
        """Establish replication connection"""
        try:
            conn_str = (
                f"dbname='{DB_CONFIG['dbname']}' "
                f"host='{DB_CONFIG['host']}' "
                f"user='{DB_CONFIG['user']}' "
                f"password='{DB_CONFIG['password']}' "
                f"port={DB_CONFIG['port']}"
            )
            
            self.replication_conn = psycopg2.connect(
                conn_str,
                connection_factory=LogicalReplicationConnection
            )
            self.cursor = self.replication_conn.cursor()
            
            self.logger.info("Replication connection established")
        
        except Exception as e:
            self.logger.error(f"Error connecting to database: {e}")
            raise
    
    def _load_last_lsn(self) -> Optional[str]:
        """Load last processed LSN from disk"""
        lsn_file = "last_lsn.txt"
        
        if os.path.exists(lsn_file):
            try:
                with open(lsn_file, 'r') as f:
                    lsn = f.read().strip()
                    self.logger.info(f"Loaded last LSN: {lsn}")
                    return lsn
            except Exception as e:
                self.logger.error(f"Error loading last LSN: {e}")
        
        return None
    
    def _save_last_lsn(self, lsn: str):
        """Save last processed LSN to disk"""
        try:
            with open("last_lsn.txt", 'w') as f:
                f.write(lsn)
        except Exception as e:
            self.logger.error(f"Error saving last LSN: {e}")
    
    def get_slot_info(self) -> dict:
        """Get information about the replication slot"""
        try:
            # We need a separate query cursor for this
            with self.replication_conn.cursor() as cur:
                cur.execute(
                    "SELECT active, active_pid, restart_lsn FROM pg_replication_slots WHERE slot_name = %s",
                    (self.slot_name,)
                )
                row = cur.fetchone()
                if row:
                    return {
                        'exists': True,
                        'active': row[0],
                        'active_pid': row[1],
                        'restart_lsn': row[2]
                    }
                return {'exists': False}
        except Exception as e:
            self.logger.error(f"Error checking slot info: {e}")
            return {'exists': False, 'error': str(e)}

    def create_replication_slot(self):
        """Create replication slot if it doesn't exist"""
        # First check if it exists logic manually to give better feedback
        slot_info = self.get_slot_info()
        
        if slot_info.get('exists'):
            if slot_info.get('active'):
                self.logger.warning(f"Replication slot '{self.slot_name}' already exists and is ACTIVE (PID {slot_info['active_pid']})")
            else:
                self.logger.info(f"Replication slot '{self.slot_name}' already exists and is inactive (Ready to use)")
            return

        try:
            # Check for temporary slot configuration
            is_temporary = REPLICATION_CONFIG.get('temporary', False)
            
            if is_temporary:
                self.logger.info(f"Creating TEMPORARY replication slot '{self.slot_name}'")
                # Use raw SQL to create a temporary slot ON THE REPLICATION CONNECTION
                # This ensures it is visible to the streaming session
                with self.replication_conn.cursor() as cur:
                    try:
                        # pg_create_logical_replication_slot(slot_name, plugin, temporary?)
                        # Postgres 10+ supports temporary slots via SQL interface
                        cur.execute(f"SELECT pg_create_logical_replication_slot('{self.slot_name}', '{self.output_plugin}', true)")
                        self.logger.info(f"Temporary replication slot '{self.slot_name}' created successfully on replication connection")
                    except psycopg2.errors.DuplicateObject:
                        self.logger.info(f"Temporary slot '{self.slot_name}' already exists (session re-use?)")
                    except Exception as e:
                        self.logger.error(f"Failed to create temporary slot: {e}")
                        raise
                return

            self.cursor.create_replication_slot(
                self.slot_name,
                output_plugin=self.output_plugin
            )
            self.logger.info(f"Replication slot '{self.slot_name}' created successfully")
        
        except psycopg2.errors.DuplicateObject:
            # Should be caught by get_slot_info but race conditions exist
            self.logger.info(f"Replication slot '{self.slot_name}' already exists")
        
        except Exception as e:
            self.logger.error(f"Error creating replication slot: {e}")
            raise
    
    def start_replication(self):
        """Start replication from last known LSN or beginning"""
        try:
            # Start replication without explicit LSN - let it resume from slot position
            self.cursor.start_replication(
                slot_name=self.slot_name,
                decode=True
            )
            
            if self.last_lsn:
                self.logger.info(f"Resuming replication from last known LSN: {self.last_lsn}")
            else:
                self.logger.info("Started replication from beginning")
        
        except Exception as e:
            self.logger.error(f"Error starting replication: {e}")
            raise
    
    def consume_changes(self):
        """
        Consume replication stream and process changes with PITR tracking
        """
        def consume(message):
            try:
                if self.shutdown_requested:
                    self.logger.info("Shutdown requested, stopping replication")
                    raise KeyboardInterrupt
                
                # Extract LSN
                lsn = message.data_start
                lsn_str = f"{lsn >> 32}/{lsn & 0xFFFFFFFF}"
                
                # Decode payload
                payload = message.payload
                if isinstance(payload, bytes):
                    payload = payload.decode('utf-8')
                
                payload = payload.strip()
                
                # Skip empty messages
                if not payload:
                    message.cursor.send_feedback(flush_lsn=message.data_start)
                    return
                
                # Process message
                self._process_message(lsn_str, payload)
                
                # Send feedback
                message.cursor.send_feedback(flush_lsn=message.data_start)
                
                # Save LSN periodically
                self.last_lsn = lsn_str
                self._save_last_lsn(lsn_str)
            
            except KeyboardInterrupt:
                raise
            except Exception as e:
                self.logger.error(f"Error processing message: {e}")
        
        self.logger.info("Starting to consume changes...")
        
        try:
            self.cursor.consume_stream(consume)
        
        except KeyboardInterrupt:
            self.logger.info("Replication stopped by user")
        
        except Exception as e:
            self.logger.error(f"Error consuming stream: {e}")
            raise
        
        finally:
            self._shutdown()
    
    def _process_message(self, lsn: str, payload: str):
        """
        Process a replication message and extract change data
        
        Args:
            lsn: Log Sequence Number
            payload: Message payload
        """
        # Handle transaction control messages
        if payload.startswith('BEGIN'):
            self._handle_begin(lsn, payload)
        
        elif payload.startswith('COMMIT'):
            self._handle_commit(lsn, payload)
        
        elif payload.startswith('ROLLBACK'):
            self._handle_rollback(lsn, payload)
        
        # Handle data change messages
        elif payload.startswith('table'):
            self._handle_table_change(lsn, payload)
        
        else:
            self.logger.debug(f"Unhandled message type: {payload[:50]}")
    
    def _handle_begin(self, lsn: str, payload: str):
        """Handle BEGIN transaction message"""
        # Extract transaction ID
        # Format: "BEGIN 12345"
        match = re.search(r'BEGIN (\d+)', payload)
        if match:
            txid = int(match.group(1))
            self.current_txid = txid
            
            self.transaction_manager.begin_transaction(
                txid=txid,
                lsn=lsn,
                timestamp=datetime.now()
            )
            
            self.logger.debug(f"Transaction {txid} started at LSN {lsn}")
    
    def _handle_commit(self, lsn: str, payload: str):
        """Handle COMMIT transaction message"""
        if self.current_txid:
            self.transaction_manager.commit_transaction(
                txid=self.current_txid,
                lsn=lsn,
                timestamp=datetime.now()
            )
            
            self.logger.info(f"Transaction {self.current_txid} committed at LSN {lsn}")
            
            # Flush changes to disk on commit to ensure transaction-consistent backup
            self.logger.info(f"Triggering backup flush for transaction {self.current_txid}")
            self.backup_manager.force_flush()
            
            self.current_txid = None
        else:
            self.logger.warning("COMMIT without active transaction")
    
    def _handle_rollback(self, lsn: str, payload: str):
        """Handle ROLLBACK transaction message"""
        if self.current_txid:
            self.transaction_manager.rollback_transaction(
                txid=self.current_txid,
                lsn=lsn,
                timestamp=datetime.now()
            )
            
            self.logger.info(f"Transaction {self.current_txid} rolled back at LSN {lsn}")
            
            # Still flush to ensure transaction log is persistent
            self.backup_manager.force_flush()
            
            self.current_txid = None
        else:
            self.logger.warning("ROLLBACK without active transaction")
    
    def _handle_table_change(self, lsn: str, payload: str):
        """
        Handle table change message
        
        Format examples (test_decoding):
        table public.users: INSERT: id[integer]:1 name[text]:'John'
        table public.users: UPDATE: id[integer]:1 name[text]:'Jane'
        table public.users: DELETE: id[integer]:1
        """
        try:
            change_data = self._parse_change_data(payload)
            
            if not change_data:
                return
            
            # Use current transaction ID or create implicit one
            txid = self.current_txid or hash(lsn) % (2**31)
            
            # Track change in backup manager
            self.backup_manager.track_change(
                lsn=lsn,
                txid=txid,
                timestamp=datetime.now(),
                table_name=change_data['table'],
                operation=change_data['operation'],
                data=change_data['data'],
                old_data=change_data.get('old_data')
            )
            
            self.logger.info(
                f"Captured {change_data['operation']} on {change_data['table']} "
                f"(LSN: {lsn}, TxID: {txid})"
            )
        
        except Exception as e:
            self.logger.error(f"Error handling table change: {e}\nPayload: {payload}")
    
    def _parse_change_data(self, payload: str) -> Optional[Dict[str, Any]]:
        """
        Parse change data from test_decoding format
        
        Args:
            payload: Raw payload string
        
        Returns:
            Dictionary with parsed change data
        """
        try:
            # Format: "table schema.table_name: OPERATION: col1[type]:val1 ..."
            # For UPDATEs (with options): "table ...: UPDATE: old-key: ... new-tuple: ..."
            
            parts = payload.split(':', 2)
            
            if len(parts) < 3:
                return None
            
            # Extract table name
            table_part = parts[0].strip()
            table_match = re.search(r'table\s+(\S+)', table_part)
            if not table_match:
                return None
            
            table_name = table_match.group(1)
            
            # Extract operation
            operation = parts[1].strip()
            
            # Extract data
            data_part = parts[2].strip()
            
            data = None
            old_data = None
            
            if operation == 'UPDATE':
                # Check for old-key / new-tuple format
                # This depends on REPLICA IDENTITY and plugin output
                # Common pattern: "old-key: ... new-tuple: ..."
                
                # Try to split by "new-tuple:" first
                if "new-tuple:" in data_part:
                    segments = data_part.split("new-tuple:")
                    old_segment = segments[0].replace("old-key:", "").strip()
                    new_segment = segments[1].strip()
                    
                    old_data = self._parse_column_data(old_segment)
                    data = self._parse_column_data(new_segment)
                else:
                    # Standard fallback (might merge them or only have new data)
                    data = self._parse_column_data(data_part)
            else:
                # INSERT / DELETE
                data = self._parse_column_data(data_part)
                
                # For DELETE, the data is technically the "old key"
                if operation == 'DELETE':
                    old_data = data
                    data = data  # Keep it in data as well for compatibility
            
            return {
                'table': table_name,
                'operation': operation,
                'data': data,
                'old_data': old_data
            }
        
        except Exception as e:
            self.logger.error(f"Error parsing change data: {e}")
            return None
    
    def _parse_column_data(self, data_str: str) -> Dict[str, Any]:
        """
        Parse column data from test_decoding format
        
        Format: "col1[type]:val1 col2[type]:val2"
        """
        data = {}
        
        # Split by spaces, but handle quoted values
        pattern = r"(\w+)\[([^\]]+)\]:('(?:[^']|'')*'|[^\s]+)"
        matches = re.findall(pattern, data_str)
        
        for col_name, col_type, col_value in matches:
            # Remove quotes from string values
            if col_value.startswith("'") and col_value.endswith("'"):
                col_value = col_value[1:-1].replace("''", "'")
            
            # Convert to appropriate type
            if col_value == 'null':
                col_value = None
            elif col_type in ('integer', 'bigint', 'smallint'):
                col_value = int(col_value) if col_value else None
            elif col_type in ('numeric', 'decimal', 'real', 'double precision'):
                col_value = float(col_value) if col_value else None
            elif col_type == 'boolean':
                col_value = col_value.lower() == 'true' if col_value else None
            
            data[col_name] = col_value
        
        return data
    
    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signal"""
        self.logger.info(f"Received shutdown signal: {signum}")
        self.shutdown_requested = True
    
    def _shutdown(self):
        """Graceful shutdown"""
        self.logger.info("Shutting down CDC Processor...")
        
        # Flush backup manager
        self.backup_manager.shutdown()
        
        # Save final LSN
        if self.last_lsn:
            self._save_last_lsn(self.last_lsn)
        
        # Close connections
        if self.cursor:
            self.cursor.close()
        if self.replication_conn:
            self.replication_conn.close()
        
        self.logger.info("Shutdown complete")
    
    def get_statistics(self) -> dict:
        """Get CDC and backup statistics"""
        return {
            'last_lsn': self.last_lsn,
            'current_txid': self.current_txid,
            'backup_stats': self.backup_manager.get_statistics(),
            'transaction_stats': self.transaction_manager.get_statistics()
        }

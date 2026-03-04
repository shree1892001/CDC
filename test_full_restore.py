
import sys
import os
import time
import psycopg2
from datetime import datetime, timedelta
import logging

# Add current directory to path
sys.path.append('d:\\CDC')

from services.PITRBackupManager import PITRBackupManager
from services.PITRRestoreManager import PITRRestoreManager
from services.pitr_config import DB_CONFIG, PITR_CONFIG

# Configure logging to stdout
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("FullRestoreTest")

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

def run_test():
    logger.info("Starting Full Restore Test...")
    
    conn = get_db_connection()
    conn.autocommit = True
    cursor = conn.cursor()
    
    # 1. Setup Test Data
    table_name = "restore_test_kv"
    logger.info(f"Creating test table {table_name}...")
    cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
    cursor.execute(f"CREATE TABLE {table_name} (key VARCHAR(50) PRIMARY KEY, value VARCHAR(50))")
    
    cursor.execute(f"INSERT INTO {table_name} VALUES ('k1', 'v1')")
    cursor.execute(f"INSERT INTO {table_name} VALUES ('k2', 'v2')")
    logger.info("Inserted initial data (k1:v1, k2:v2)")
    
    # Initialize managers
    backup_manager = PITRBackupManager()
    restore_manager = PITRRestoreManager(backup_manager=backup_manager)
    
    # Force flush any existing buffer
    backup_manager.force_flush()
    
    # 2. Create Base Backup
    logger.info("Creating BASE BACKUP...")
    # This captures k1:v1, k2:v2
    # Ensure a delay so timestamps are distinct
    time.sleep(1)
    backup_manager.create_base_backup(DB_CONFIG['dbname'])
    time.sleep(1)
    
    # 3. Create Incremental Changes
    logger.info("Creating incremental changes...")
    cursor.execute(f"INSERT INTO {table_name} VALUES ('k3', 'v3')")
    cursor.execute(f"UPDATE {table_name} SET value = 'v2_updated' WHERE key = 'k2'")
    logger.info("Executed SQL: Inserted k3 and updated k2")
    
    # We need to simulate the change tracking (normally done by CDC listener)
    # We'll manually track these changes in the backup manager for the test.
    # We need valid LSNs for this to work properly with the managers.
    cursor.execute("SELECT pg_current_wal_lsn()")
    current_lsn = cursor.fetchone()[0]
    
    txid = 1001
    timestamp = datetime.now()
    
    # Track INSERT k3
    backup_manager.track_change(
        lsn=current_lsn, 
        txid=txid,
        timestamp=timestamp,
        table_name=table_name,
        operation='INSERT',
        data={'key': 'k3', 'value': 'v3'}
    )
    
    # Track UPDATE k2
    backup_manager.track_change(
        lsn=current_lsn,
        txid=txid,
        timestamp=timestamp,
        table_name=table_name,
        operation='UPDATE',
        data={'key': 'k2', 'value': 'v2_updated'},
        old_data={'key': 'k2', 'value': 'v2'} 
    )
    
    # Flush changes to disk
    backup_manager.force_flush()
    logger.info("Flushed incremental changes to backup.")
    
    # Wait a bit
    time.sleep(1)
    restore_target_time = datetime.now()
    logger.info(f"Restore Target Time: {restore_target_time}")
    
    # 4. Simulate Disaster
    logger.info("Simulating disaster (Dropping table)...")
    cursor.execute(f"DROP TABLE {table_name}")
    conn.close()
    
    # 5. Restore
    logger.info("Starting RESTORE process...")
    # Note: restore might fail if other connections are open to the DB.
    # In a real scenario, we'd stop the app. Here we just closed our own connection.
    
    try:
        result = restore_manager.restore_to_timestamp(
            target_timestamp=restore_target_time,
            target_db=DB_CONFIG['dbname']
        )
        
        if result['success']:
            logger.info("Restore reported SUCCESS.")
        else:
            logger.error(f"Restore FAILED: {result.get('error')}")
            # Continue to verification to see what happened
            
    except Exception as e:
        logger.error(f"Restore threw exception: {e}")
        import traceback
        traceback.print_exc()

    # 6. Verify Data
    logger.info("Verifying restored data...")
    try:    
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(f"SELECT * FROM {table_name} ORDER BY key")
        rows = cursor.fetchall()
        
        # Expected: k1:v1, k2:v2_updated, k3:v3 (if incremental worked)
        # Or k1:v1, k2:v2 (if only base worked)
        
        expected_full = [('k1', 'v1'), ('k2', 'v2_updated'), ('k3', 'v3')]
        expected_base = [('k1', 'v1'), ('k2', 'v2')]
        
        logger.info(f"Restored Data: {rows}")
        
        if rows == expected_full:
            logger.info("VERIFICATION SUCCESSFUL: Full restore (Base + Incremental) worked!")
            print("TEST PASSED")
        elif rows == expected_base:
            logger.warning("VERIFICATION PARTIAL: Base restore worked, but incremental changes are missing.")
            print("TEST PARTIAL FIX")
        else:
            logger.error(f"VERIFICATION FAILED: Data mismatch.")
            logger.error(f"Expected: {expected_full}")
            logger.error(f"Actual:   {rows}")
            print("TEST FAILED")
            
    except Exception as e:
        logger.error(f"Verification queries failed: {e}")
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    run_test()

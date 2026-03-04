"""
Main entry point for CDC with PITR
Simple execution without arguments.
Just run: python main_pitr.py
"""

import sys
from datetime import datetime, timedelta
from services.CDCProcessorPITR import CDCProcessor
from services.pitr_config import DB_CONFIG

def main():
    print("-" * 60)
    print("Starting CDC Processor with PITR (Simple Mode)")
    print("-" * 60)
    
    # Initialize CDC processor with default settings
    cdc_processor = CDCProcessor()
    
    try:
        # 1. Check for Base Backup (Auto-create if needed)
        # This ensures we always have a base state to restore from
        print("Checking for existing base backup...")
        latest_base = cdc_processor.backup_manager.get_latest_base_backup()
        
        should_backup = False
        if not latest_base:
            print(">> No base backup found. Creating initial base backup...")
            should_backup = True
        else:
            base_time = datetime.fromisoformat(latest_base['timestamp'])
            age = datetime.now() - base_time
            print(f">> Found recent base backup: {latest_base['filename']}")
            print(f"   Created at: {base_time} (Age: {age})")
            
            # Create a new base backup if the last one is older than 1 day
            # This keeps restore times reasonable (fewer incremental changes to apply)
            if age > timedelta(days=1):
                print(">> Latest base backup is > 24 hours old. Creating new base backup...")
                should_backup = True
        
        if should_backup:
            try:
                result = cdc_processor.backup_manager.create_base_backup(
                    target_db=DB_CONFIG['dbname']
                )
                print(f">> Base backup created successfully: {result['filename']}")
            except Exception as e:
                print(f"WARNING: Failed to create base backup: {e}")
                print("Continuing with incremental backup only (RESTORE MAY BE INCOMPLETE)")

        # 2. Create replication slot (safely skips if already exists)
        cdc_processor.create_replication_slot()
        
        # 3. Start replication
        print("\nStarting replication stream...")
        try:
            cdc_processor.start_replication()
        except Exception as e:
            import psycopg2.errors
            if isinstance(e, psycopg2.errors.ObjectInUse):
                print(f"\n[ERROR] Replication slot '{cdc_processor.slot_name}' is currently active.")
                print("This means another CDC process is already running.")
                # Try to get info about the active process
                slot_info = cdc_processor.get_slot_info()
                if slot_info.get('active'):
                    print(f"Active PID: {slot_info['active_pid']}")
                    print(f"To fix this: Stop the process with PID {slot_info['active_pid']} or wait for it to finish.")
                    print(f"Command: taskkill /F /PID {slot_info['active_pid']}")
                else:
                    print("Could not determine active PID. Please check Task Manager for python processes.")
                return 1
            else:
                raise e
        
        # 4. Consume changes
        print("CDC Processor is running. Press Ctrl+C to stop.")
        print("=" * 60)
        cdc_processor.consume_changes()
    
    except KeyboardInterrupt:
        print("\nStopped by user")
        return 0
    
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
"""
Automatic Backup Restoration Daemon
Runs alongside main.py and automatically restores incremental backups to a test database

Usage:
    python auto_restore.py [--test-db test_db_name] [--interval 10]

If no test database is specified, one will be derived from the production database name
with suffix '_restore_test'
"""

import sys
import argparse
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from services.AutoRestoreManager import AutoRestoreManager


def main():
    parser = argparse.ArgumentParser(
        description='Automatic Backup Restoration Daemon',
        epilog="""
Examples:
  # Auto-restore to default test DB (mydb_restore_test)
  python auto_restore.py
  
  # Auto-restore to specific test DB
  python auto_restore.py --test-db my_test_restore
  
  # Check for new backups every 5 seconds
  python auto_restore.py --interval 5
        """
    )
    
    parser.add_argument(
        '--test-db',
        help='Target test database name for auto-restore (default: <production_db>_restore_test)'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=10,
        help='Monitor interval in seconds (default: 10)'
    )
    
    args = parser.parse_args()
    
    print("AUTOMATIC BACKUP RESTORATION DAEMON")
    print("-" * 70)
    print(f"Test database:   {args.test_db or 'auto-derived'}")
    print(f"Monitor interval: {args.interval}s")
    print()
    print("This daemon monitors the backup directory and automatically restores")
    print("incremental backups to a test database for verification.")
    print()
    print("Press Ctrl+C to stop.")
    print("-" * 70)
    print()
    
    # Create and start the auto-restore manager
    manager = AutoRestoreManager(
        test_db_name=args.test_db,
        monitor_interval=args.interval
    )
    manager.start()
    
    try:
        # Keep the daemon running
        import time
        last_count = 0
        last_time = None
        while True:
            time.sleep(1)
            
            # Periodically print status only when it changes
            status = manager.get_status()
            count = status['processed_backups']
            if count > 0 and (count != last_count or status['last_restore_time'] != last_time):
                last_restore = status['last_restore_time'] or 'never'
                print(f"[{last_restore}] Processed {count} backup(s)")
                last_count = count
                last_time = status['last_restore_time']
        manager.stop()
        print("Daemon stopped.")
        return 0
    
    except Exception as e:
        print(f"\n[Error] {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())

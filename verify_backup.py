import sys
import os
import subprocess

# Add current directory to path
sys.path.append('d:\\CDC')

from services.PITRBackupManager import PITRBackupManager
from services.pitr_config import PITR_CONFIG

def verify_backup():
    print(f"Configured Base Backup Format: {PITR_CONFIG.get('base_backup_format')}")
    
    manager = PITRBackupManager()
    
    print("Attempting to create base backup...")
    try:
        # We need a valid DB connection for this to work.
        # If it fails, we will catch it.
        snapshot = manager.create_base_backup('test') # Try default 'test' db
        print(f"Backup created: {snapshot['path']}")
        
        # Verify with pg_restore list
        print("Verifying with pg_restore --list ...")
        cmd = ['pg_restore', '--list', snapshot['path']]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("SUCCESS: pg_restore accepted the file.")
            print("Archive content preview:")
            print("\n".join(result.stdout.splitlines()[:5]))
        else:
            print("FAILURE: pg_restore rejected the file.")
            print(result.stderr)
            
    except Exception as e:
        print(f"Error executing backup: {e}")

if __name__ == "__main__":
    verify_backup()

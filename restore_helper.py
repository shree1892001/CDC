
import subprocess
import sys
import os
from pathlib import Path

# Add services to path
sys.path.insert(0, str(Path(__file__).parent))
from services.pitr_config import DB_CONFIG

def run_restore(file_path):
    path = Path(file_path)
    if not path.exists():
        print(f"Error: File not found: {file_path}")
        return
    
    # Identify type by extension/content
    is_sql = path.suffix.lower() == '.sql'
    
    # Prepare environment with password
    env = os.environ.copy()
    if DB_CONFIG.get('password'):
        env['PGPASSWORD'] = DB_CONFIG['password']
    
    if is_sql:
        print(f"[*] Detected SQL Incremental Backup: {path.name}")
        print("[*] Using 'psql' to apply changes...")
        cmd = [
            'psql',
            '-h', DB_CONFIG['host'],
            '-p', str(DB_CONFIG['port']),
            '-U', DB_CONFIG['user'],
            '-d', DB_CONFIG['dbname'],
            '-f', str(path)
        ]
    else:
        print(f"[*] Detected Binary Base Snapshot: {path.name}")
        print("[*] Using 'pg_restore' to restore snapshot...")
        cmd = [
            'pg_restore',
            '-h', DB_CONFIG['host'],
            '-p', str(DB_CONFIG['port']),
            '-U', DB_CONFIG['user'],
            '-d', DB_CONFIG['dbname'],
            '--clean', '--if-exists',
            str(path)
        ]
    
    print(f"[>] Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode == 0:
            print("\n✅ Restore successful!")
        else:
            print("\n❌ Restore failed!")
            print(result.stderr)
    except FileNotFoundError:
        print("\n❌ Error: PostgreSQL tools (psql/pg_restore) not found in PATH.")
        print("Please ensure PostgreSQL 'bin' folder is in your system PATH.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python restore_helper.py <path_to_backup_file>")
        sys.exit(1)
    
    run_restore(sys.argv[1])

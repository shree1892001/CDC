"""Utility to produce a single SQL file containing a base backup followed by all needed incrementals.

Usage:
    python combine_backups.py --timestamp "2026-03-03 19:00:00" --output combined.sql

The resulting file can be restored manually with a single psql invocation.
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

# make sure services package is importable
sys.path.insert(0, str(Path(__file__).parent))

from services.PITRBackupManager import PITRBackupManager
from services.EnhancedBackupManager import BackupChainBuilder
from services.pitr_config import PITR_CONFIG


def main():
    parser = argparse.ArgumentParser(description="Combine base + incremental backups into one SQL file")
    parser.add_argument('--timestamp', required=True, help='Target timestamp (YYYY-MM-DD HH:MM:SS) to restore to')
    parser.add_argument('--output', required=True, help='Path to write the combined SQL file')
    args = parser.parse_args()

    ts = datetime.fromisoformat(args.timestamp)

    backup_manager = PITRBackupManager()
    catalog = backup_manager.backup_catalog
    chain_builder = BackupChainBuilder(catalog)
    chain = chain_builder.build_chain_to_point(ts)

    if not chain:
        print("No backups found for the specified timestamp")
        sys.exit(1)

    out_path = Path(args.output)
    with open(out_path, 'wb') as out_f:
        for b in chain:
            file_path = Path(PITR_CONFIG['backup_dir']) / b['filename']
            if not file_path.exists():
                print(f"WARNING: backup file missing: {file_path}")
                continue
            print(f"Appending {file_path}")
            with open(file_path, 'rb') as in_f:
                out_f.write(in_f.read())
                out_f.write(b"\n\n")

    print(f"Combined {len(chain)} backups into {out_path}")


if __name__ == '__main__':
    main()

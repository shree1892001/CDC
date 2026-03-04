"""
PITR Restore CLI Tool
Command-line interface for point-in-time recovery operations
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from tabulate import tabulate

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from services.PITRRestoreManager import PITRRestoreManager
from services.PITRBackupManager import PITRBackupManager
from services.EnhancedRestoreManager import EnhancedPITRRestoreManager
from services.TransactionLogManager import TransactionLogManager
from services.pitr_config import DB_CONFIG


def format_timestamp(ts_str: str) -> str:
    """Format timestamp for display"""
    try:
        dt = datetime.fromisoformat(ts_str)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return ts_str


def check_file_type(file_path: str) -> tuple[str, str, str]:
    """
    Determine file type and appropriate restore command
    Returns: (file_type, recommendation, tool_command)
    """
    path = Path(file_path)
    if not path.exists():
        return "error", "File not found", ""

    # Check header
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            header = f.read(100)
            
        if header.startswith('PGDMP'):
            return (
                "PostgreSQL Custom Archive (.dump)", 
                "Use pg_restore to restore this file.",
                f"pg_restore -h {DB_CONFIG['host']} -p {DB_CONFIG['port']} -U {DB_CONFIG['user']} -d {DB_CONFIG['dbname']} --clean --if-exists \"{file_path}\""
            )
        elif "-- PostgreSQL CDC Incremental Backup" in header or "INSERT INTO" in header or "BEGIN;" in header:
             return (
                "PostgreSQL SQL Script (.sql)", 
                "Use psql or restore_cli.py to restore this file. DO NOT use pg_restore.",
                f"psql -h {DB_CONFIG['host']} -p {DB_CONFIG['port']} -U {DB_CONFIG['user']} -d {DB_CONFIG['dbname']} -f \"{file_path}\""
            )
        else:
             return (
                "Unknown/Plain Text", 
                "Likely an SQL script if it contains SQL commands. Try psql.",
                f"psql -h {DB_CONFIG['host']} -p {DB_CONFIG['port']} -U {DB_CONFIG['user']} -d {DB_CONFIG['dbname']} -f \"{file_path}\""
            )
    except Exception as e:
        return "error", f"Error reading file: {e}", ""


def cmd_check_file(args):
    """Check a backup file and recommend restore method"""
    print(f"Checking file: {args.file}")
    print("-" * 60)
    
    file_type, recommendation, command = check_file_type(args.file)
    
    if file_type == "error":
        print(f"❌ Error: {recommendation}")
        return 1
        
    print(f"File Type:      {file_type}")
    print(f"Recommendation: {recommendation}")
    print("\nSuggested Command:")
    print(f"  {command}")
    
    return 0


def cmd_list_backups(args):
    """List available backups"""
    backup_manager = PITRBackupManager()
    
    if args.start_time:
        start_time = datetime.fromisoformat(args.start_time)
    else:
        start_time = None
    
    if args.end_time:
        end_time = datetime.fromisoformat(args.end_time)
    else:
        end_time = None
    
    backups = backup_manager.list_backups_in_range(start_time, end_time)
    
    if not backups:
        print("No backups found.")
        return
    
    # Format for display
    table_data = []
    for backup in backups:
        table_data.append([
            backup['backup_id'],
            format_timestamp(backup['start_time']),
            format_timestamp(backup.get('end_time', 'In Progress')),
            backup['changes_count'],
            ', '.join(backup.get('tables_affected', []))[:50]
        ])
    
    headers = ['Backup ID', 'Start Time', 'End Time', 'Changes', 'Tables']
    print(tabulate(table_data, headers=headers, tablefmt='grid'))
    print(f"\nTotal backups: {len(backups)}")


def cmd_list_recovery_points(args):
    """List available recovery points"""
    restore_manager = PITRRestoreManager()
    
    if args.start_time:
        start_time = datetime.fromisoformat(args.start_time)
    else:
        start_time = None
    
    if args.end_time:
        end_time = datetime.fromisoformat(args.end_time)
    else:
        end_time = None
    
    recovery_points = restore_manager.list_available_restore_points(start_time, end_time)
    
    if not recovery_points:
        print("No recovery points found.")
        return
    
    # Format for display
    table_data = []
    for point in recovery_points:
        table_data.append([
            point['txid'],
            format_timestamp(point['timestamp']),
            point['lsn'],
            point['changes_count'],
            ', '.join(point.get('tables_affected', []))[:50]
        ])
    
    headers = ['TxID', 'Timestamp', 'LSN', 'Changes', 'Tables']
    print(tabulate(table_data, headers=headers, tablefmt='grid'))
    print(f"\nTotal recovery points: {len(recovery_points)}")


def cmd_preview_restore(args):
    """Preview a restore operation"""
    restore_manager = PITRRestoreManager()
    
    target_timestamp = datetime.fromisoformat(args.timestamp)
    
    print(f"Previewing restore to: {format_timestamp(args.timestamp)}")
    print("-" * 60)
    
    preview = restore_manager.preview_restore(target_timestamp)
    
    if not preview['valid']:
        print(f"❌ Invalid restore point: {preview['message']}")
        return 1
    
    print(f"✅ {preview['message']}")
    print()
    print(f"Target timestamp:        {format_timestamp(preview['target_timestamp'])}")
    print(f"Actual restore time:     {format_timestamp(preview['actual_restore_timestamp'])}")
    print(f"Recovery point LSN:      {preview['recovery_point']['lsn']}")
    print(f"Recovery point TxID:     {preview['recovery_point']['txid']}")
    print()
    print(f"Backups to process:      {preview['backups_to_process']}")
    print(f"Total changes to apply:  {preview['total_changes_to_apply']}")
    print(f"Tables affected:         {', '.join(preview['tables_affected'])}")
    print()
    print("Backup IDs:")
    for backup_id in preview['backup_ids']:
        print(f"  - {backup_id}")
    
    return 0


def cmd_restore(args):
    """Perform a restore operation"""
    restore_manager = PITRRestoreManager()
    
    target_timestamp = datetime.fromisoformat(args.timestamp)
    
    print(f"Starting restore to: {format_timestamp(args.timestamp)}")
    print(f"Target database: {args.target_db}")
    
    if args.tables:
        print(f"Tables to restore: {', '.join(args.tables)}")
    else:
        print("Restoring all tables")
    
    print("-" * 60)
    
    # Confirm if not dry run
    if not args.dry_run and not args.yes:
        response = input("\n⚠️  This will modify the target database. Continue? (yes/no): ")
        if response.lower() != 'yes':
            print("Restore cancelled.")
            return 1
    
    # Perform restore
    result = restore_manager.restore_to_timestamp(
        target_timestamp=target_timestamp,
        target_db=args.target_db,
        tables=args.tables,
        dry_run=args.dry_run
    )
    
    if result['success']:
        if args.dry_run:
            print("\n✅ Dry run completed successfully")
            print("\nPreview:")
            preview = result['preview']
            print(f"  Changes to apply: {preview['total_changes_to_apply']}")
            print(f"  Tables affected:  {', '.join(preview['tables_affected'])}")
        else:
            print("\n✅ Restore completed successfully")
            print(f"\n  Changes applied:  {result['changes_applied']}")
            print(f"  Tables restored:  {', '.join(result['tables_restored'])}")
            print(f"  Restore time:     {format_timestamp(result['restore_timestamp'])}")
        
        return 0
    else:
        print(f"\n❌ Restore failed: {result.get('error', 'Unknown error')}")
        return 1


def cmd_restore_lsn(args):
    """Restore to a specific LSN"""
    restore_manager = PITRRestoreManager()
    
    print(f"Starting restore to LSN: {args.lsn}")
    print(f"Target database: {args.target_db}")
    print("-" * 60)
    
    # Confirm if not dry run
    if not args.dry_run and not args.yes:
        response = input("\n⚠️  This will modify the target database. Continue? (yes/no): ")
        if response.lower() != 'yes':
            print("Restore cancelled.")
            return 1
    
    # Perform restore
    result = restore_manager.restore_to_lsn(
        target_lsn=args.lsn,
        target_db=args.target_db,
        tables=args.tables,
        dry_run=args.dry_run
    )
    
    if result['success']:
        if args.dry_run:
            print("\n✅ Dry run completed successfully")
        else:
            print("\n✅ Restore completed successfully")
            print(f"\n  Changes applied: {result['changes_applied']}")
            print(f"  Tables restored: {', '.join(result['tables_restored'])}")
        
        return 0
    else:
        print(f"\n❌ Restore failed: {result.get('error', 'Unknown error')}")
        return 1


def cmd_restore_chain(args):
    """Perform a chain-based restore (uses backup chain and verification)"""
    restore_manager = EnhancedPITRRestoreManager()

    target_timestamp = datetime.fromisoformat(args.timestamp)

    print(f"Starting chain restore to: {format_timestamp(args.timestamp)}")
    print(f"Target database: {args.target_db}")

    if args.tables:
        print(f"Tables to restore: {', '.join(args.tables)}")
    else:
        print("Restoring all tables")

    print("-" * 60)

    # Confirm if not dry run
    if not args.dry_run and not args.yes:
        response = input("\n⚠️  This will modify the target database. Continue? (yes/no): ")
        if response.lower() != 'yes':
            print("Restore cancelled.")
            return 1

    # Perform chain restore
    result = restore_manager.restore_to_timestamp_with_chain(
        target_timestamp=target_timestamp,
        target_db=args.target_db,
        tables=args.tables,
        dry_run=args.dry_run,
        verify=args.verify
    )

    if result['success']:
        if args.dry_run:
            print("\n✅ Dry run completed successfully")
            preview = result.get('preview')
            if preview:
                print(f"  Changes to apply: {preview.get('total_changes_to_apply', 0)}")
        else:
            print("\n✅ Chain restore completed successfully")
            print(f"\n  Changes applied: {result.get('changes_applied')}")
            print(f"  Tables restored: {', '.join(result.get('tables_restored', []))}")

        return 0
    else:
        print(f"\n❌ Chain restore failed: {result.get('error', 'Unknown error')}")
        return 1


def cmd_statistics(args):
    """Show backup and transaction statistics"""
    backup_manager = PITRBackupManager()
    transaction_manager = TransactionLogManager()
    
    backup_stats = backup_manager.get_statistics()
    tx_stats = transaction_manager.get_statistics()
    
    print("=" * 60)
    print("PITR BACKUP STATISTICS")
    print("=" * 60)
    
    print("\nBackup Statistics:")
    print(f"  Total backups:        {backup_stats['total_backups']}")
    print(f"  Total changes:        {backup_stats['total_changes']}")
    print(f"  Total size:           {backup_stats['total_size_mb']:.2f} MB")
    print(f"  Current backup:       {backup_stats['current_backup_changes']} changes")
    print(f"  Buffered changes:     {backup_stats['buffered_changes']}")
    
    print("\nTransaction Statistics:")
    print(f"  Active transactions:  {tx_stats['active_transactions']}")
    print(f"  Completed:            {tx_stats['completed_transactions']}")
    print(f"  Committed:            {tx_stats['committed_transactions']}")
    print(f"  Rolled back:          {tx_stats['rolled_back_transactions']}")
    print(f"  Total changes:        {tx_stats['total_changes']}")
    
    print()


def cmd_base_backup(args):
    """Create a full base backup snapshot"""
    backup_manager = PITRBackupManager()
    
    print(f"Starting base backup for database: {args.db}")
    if args.output:
        print(f"Output path: {args.output}")
    print("-" * 60)
    
    try:
        metadata = backup_manager.create_base_backup(
            target_db=args.db,
            output_path=args.output
        )
        print(f"\n✅ Base backup created successfully!")
        print(f"  Filename: {metadata['filename']}")
        print(f"  Path:     {metadata['path']}")
        print(f"  Time:     {format_timestamp(metadata['timestamp'])}")
        return 0
    except Exception as e:
        print(f"\n❌ Base backup failed: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description='PITR Restore CLI - Point-in-Time Recovery for CDC Backups',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all backups
  python restore_cli.py list-backups
  
  # List recovery points in a time range
  python restore_cli.py list-recovery-points --start-time "2024-01-15 10:00:00"
  
  # Preview a restore
  python restore_cli.py preview --timestamp "2024-01-15 14:30:00"
  
  # Perform a restore (dry run)
  python restore_cli.py restore --timestamp "2024-01-15 14:30:00" --target-db test_restore --dry-run
  
  # Perform actual restore
  python restore_cli.py restore --timestamp "2024-01-15 14:30:00" --target-db test_restore --yes
  
  # Restore specific tables only
  python restore_cli.py restore --timestamp "2024-01-15 14:30:00" --target-db test_restore --tables users orders
  
  # Restore to specific LSN
  python restore_cli.py restore-lsn --lsn "0/12345678" --target-db test_restore
  
  # Show statistics
  python restore_cli.py stats
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Base backup command
    base_parser = subparsers.add_parser('base-backup', help='Create a full base snapshot using pg_dump')
    base_parser.add_argument('--db', required=True, help='Database to back up')
    base_parser.add_argument('--output', help='Optional output path for the SQL file')
    
    # List backups command
    list_backups_parser = subparsers.add_parser('list-backups', help='List available backups')
    list_backups_parser.add_argument('--start-time', help='Start time (YYYY-MM-DD HH:MM:SS)')
    list_backups_parser.add_argument('--end-time', help='End time (YYYY-MM-DD HH:MM:SS)')
    
    # List recovery points command
    list_recovery_parser = subparsers.add_parser('list-recovery-points', help='List available recovery points')
    list_recovery_parser.add_argument('--start-time', help='Start time (YYYY-MM-DD HH:MM:SS)')
    list_recovery_parser.add_argument('--end-time', help='End time (YYYY-MM-DD HH:MM:SS)')
    
    # Preview restore command
    preview_parser = subparsers.add_parser('preview', help='Preview a restore operation')
    preview_parser.add_argument('--timestamp', required=True, help='Target timestamp (YYYY-MM-DD HH:MM:SS)')
    
    # Restore command
    restore_parser = subparsers.add_parser('restore', help='Perform a restore operation')
    restore_parser.add_argument('--timestamp', required=True, help='Target timestamp (YYYY-MM-DD HH:MM:SS)')
    restore_parser.add_argument('--target-db', required=True, help='Target database name')
    restore_parser.add_argument('--tables', nargs='+', help='Specific tables to restore (optional)')
    restore_parser.add_argument('--dry-run', action='store_true', help='Simulate restore without making changes')
    restore_parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt')
    
    # Chain restore command (uses backup chain and verification)
    restore_chain_parser = subparsers.add_parser('restore-chain', help='Perform a chain-based restore using backup lineage and verification')
    restore_chain_parser.add_argument('--timestamp', required=True, help='Target timestamp (YYYY-MM-DD HH:MM:SS)')
    restore_chain_parser.add_argument('--target-db', required=True, help='Target database name')
    restore_chain_parser.add_argument('--tables', nargs='+', help='Specific tables to restore (optional)')
    restore_chain_parser.add_argument('--dry-run', action='store_true', help='Simulate restore without making changes')
    restore_chain_parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt')
    restore_chain_parser.add_argument('--verify', action='store_true', help='Verify backup checksums before applying')
    
    # Restore to LSN command
    restore_lsn_parser = subparsers.add_parser('restore-lsn', help='Restore to a specific LSN')
    restore_lsn_parser.add_argument('--lsn', required=True, help='Target LSN')
    restore_lsn_parser.add_argument('--target-db', required=True, help='Target database name')
    restore_lsn_parser.add_argument('--tables', nargs='+', help='Specific tables to restore (optional)')
    restore_lsn_parser.add_argument('--dry-run', action='store_true', help='Simulate restore without making changes')
    restore_lsn_parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt')
    
    # Statistics command
    stats_parser = subparsers.add_parser('stats', help='Show backup and transaction statistics')

    # Check file command
    check_parser = subparsers.add_parser('check-file', help='Check a backup file type and get restore command')
    check_parser.add_argument('file', help='Path to backup file to check')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Execute command
    try:
        if args.command == 'base-backup':
            return cmd_base_backup(args)
        elif args.command == 'list-backups':
            return cmd_list_backups(args)
        elif args.command == 'list-recovery-points':
            return cmd_list_recovery_points(args)
        elif args.command == 'preview':
            return cmd_preview_restore(args)
        elif args.command == 'restore':
            return cmd_restore(args)
        elif args.command == 'restore-lsn':
            return cmd_restore_lsn(args)
        elif args.command == 'restore-chain':
            return cmd_restore_chain(args)
        elif args.command == 'stats':
            return cmd_statistics(args)
        elif args.command == 'check-file':
            return cmd_check_file(args)
    
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())

import os
import subprocess
from datetime import datetime
import psycopg2
import schedule
import time
import logging
from threading import Thread

class DatabaseBackup:
    def __init__(self, host, user, password, database, backup_dir, logger):
        self.host = host
        self.user = user
        self.password = password
        self.database = database
        self.backup_dir = backup_dir
        self.logger = logger

    def _connect_to_db(self):
        """Create a database connection."""
        conn_params = {
            "host": self.host,
            "user": self.user,
            "password": self.password,
            "dbname": self.database,
        }
        return psycopg2.connect(**conn_params)

    def backup_full(self):
        """Perform a full database backup using pg_dump."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = os.path.join(self.backup_dir, f"full_backup_{timestamp}.sql")

        try:
            command = [
                "pg_dump",
                "-h", self.host,
                "-U", self.user,
                "-d", self.database,
                "-F", "c",
                "-f", backup_file,
            ]
            env = os.environ.copy()
            env["PGPASSWORD"] = self.password
            subprocess.run(command, check=True, env=env)
            self.logger.info(f"Full backup saved to {backup_file}")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error performing full backup: {e}")

    def detect_schema_changes(self):
        """Detect schema changes and back up schema with data."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        try:
            with self._connect_to_db() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                    """)
                    tables = [row[0] for row in cursor.fetchall()]

                    for table in tables:
                        table_backup_file = os.path.join(self.backup_dir, f"{table}_schema_backup_{timestamp}.sql")
                        command = [
                            "pg_dump",
                            "-h", self.host,
                            "-U", self.user,
                            "-d", self.database,
                            "-t", table,
                            "-F", "c",
                            "-f", table_backup_file,
                        ]
                        env = os.environ.copy()
                        env["PGPASSWORD"] = self.password
                        subprocess.run(command, check=True, env=env)
                        self.logger.info(f"Schema backup with data for table '{table}' saved to {table_backup_file}")
        except Exception as e:
            self.logger.error(f"Error detecting or backing up schema changes: {e}")

    def backup_cdc(self):
        """Backup incremental changes using logical replication and save affected tables."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        cdc_backup_file = os.path.join(self.backup_dir, f"cdc_changes_{timestamp}.txt")
        affected_tables = set()

        try:
            command = [
                "pg_recvlogical",
                "-d", self.database,
                "-U", self.user,
                "--slot", "vstatetest_slot",
                "--start",
                "-f", cdc_backup_file,
            ]
            env = os.environ.copy()
            env["PGPASSWORD"] = self.password
            subprocess.run(command, check=True, env=env)
            self.logger.info(f"CDC changes saved to {cdc_backup_file}")

            affected_tables = self._parse_cdc_log(cdc_backup_file)

            self._backup_affected_tables(affected_tables, timestamp)

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error capturing CDC changes: {e}")

    def _parse_cdc_log(self, cdc_backup_file):
        """Parse CDC log to identify affected tables."""
        affected_tables = set()
        try:
            with open(cdc_backup_file, 'r') as file:
                for line in file:
                    if "table" in line:
                        table_name = line.split("table")[1].strip().split()[0]
                        affected_tables.add(table_name)
        except Exception as e:
            self.logger.error(f"Error parsing CDC file: {e}")
        return affected_tables

    def _backup_affected_tables(self, tables, timestamp):
        """Backup affected tables in restorable SQL format."""
        for table in tables:
            table_backup_file = os.path.join(self.backup_dir, f"{table}_cdc_backup_{timestamp}.sql")
            try:
                command = [
                    "pg_dump",
                    "-h", self.host,
                    "-U", self.user,
                    "-d", self.database,
                    "-t", table,
                    "-F", "c",
                    "-f", table_backup_file,
                ]
                env = os.environ.copy()
                env["PGPASSWORD"] = self.password
                subprocess.run(command, check=True, env=env)
                self.logger.info(f"CDC backup for table '{table}' saved to {table_backup_file}")
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Error backing up table '{table}': {e}")

class CDCWatcher(Thread):
    def __init__(self, backup):
        super().__init__()
        self.backup = backup
        self.running = True

    def run(self):
        while self.running:
            self.backup.backup_cdc()  # Perform CDC backup immediately
            time.sleep(1)  # Adjust interval for your needs

    def stop(self):
        self.running = False

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("DatabaseBackup")

    backup = DatabaseBackup(
        host="localhost",
        user="postgres",
        password="postgres",
        database="test",
        backup_dir="D:\\cdc\\services\\backups",
        logger=logger,
    )

    cdc_watcher = CDCWatcher(backup)
    cdc_watcher.start()

    schedule.every(1).minute.do(backup.backup_full)
    schedule.every(1).minute.do(backup.detect_schema_changes)

    try:
        while True:
            schedule.run_pending()  # Run scheduled tasks
            time.sleep(1)
    except KeyboardInterrupt:
        cdc_watcher.stop()
        cdc_watcher.join()
        logger.info("Backup process terminated.")

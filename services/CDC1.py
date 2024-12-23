import os
import psycopg2
import logging
import json
from datetime import datetime
from psycopg2.extras import LogicalReplicationConnection

class CDCProcessor:
    def __init__(self, slot_name, output_plugin, backup_dir, state_file):
        self.slot_name = slot_name
        self.output_plugin = output_plugin
        self.backup_dir = backup_dir
        self.state_file = state_file
        self.logger = self._configure_logger()
        self.connection = self._connect_to_db(replication=True)
        self.cursor = self.connection.cursor()
        os.makedirs(self.backup_dir, exist_ok=True)
        self.last_processed = self._load_last_processed_state()

    def _configure_logger(self):
        logger = logging.getLogger("CDC_Logger")
        logger.setLevel(logging.INFO)
        file_handler = logging.FileHandler("cdc_changes.log")
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        return logger

    def _connect_to_db(self, replication=False):
        try:
            if replication:
                connection = psycopg2.connect(
                    "dbname='test' host='localhost' user='postgres' password='postgres'",
                    connection_factory=LogicalReplicationConnection
                )
            else:
                connection = psycopg2.connect(
                    "dbname='test' host='localhost' user='postgres' password='postgres'"
                )
            return connection
        except Exception as e:
            self.logger.error(f"Error connecting to the database: {e}")
            raise

    def _load_last_processed_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as file:
                    state = json.load(file)
                    return state.get("last_processed", None)
            except Exception as e:
                self.logger.error(f"Error loading last processed state: {e}")
        return None

    def _save_last_processed_state(self, last_processed):
        try:
            with open(self.state_file, 'w') as file:
                json.dump({"last_processed": last_processed}, file)
            self.logger.info(f"Last processed state saved: {last_processed}")
        except Exception as e:
            self.logger.error(f"Error saving last processed state: {e}")

    def backup_incrementally(self, table_name, changed_rows=None):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = os.path.join(self.backup_dir, f"{table_name}_backup_{timestamp}.csv")

        try:
            with self._connect_to_db(replication=False) as conn:
                with conn.cursor() as cursor:
                    if changed_rows:
                        # Backup only specific rows
                        placeholders = ', '.join(['%s'] * len(changed_rows))
                        query = f"""
                            COPY (SELECT * FROM {table_name} WHERE id IN ({placeholders}))
                            TO STDOUT WITH CSV HEADER
                        """
                        cursor.copy_expert(query, changed_rows)
                    else:
                        # Backup the entire table
                        query = f"COPY {table_name} TO STDOUT WITH CSV HEADER"
                        with open(backup_file, 'w') as file:
                            cursor.copy_expert(query, file)

            self.logger.info(f"Backup for table '{table_name}' saved to {backup_file}")
        except Exception as e:
            self.logger.error(f"Error saving backup for table '{table_name}': {e}")

    def create_replication_slot(self):
        try:
            self.cursor.create_replication_slot(self.slot_name, output_plugin=self.output_plugin)
            self.logger.info(f"Replication slot '{self.slot_name}' created.")
        except psycopg2.errors.DuplicateObject:
            self.logger.warning(f"Replication slot '{self.slot_name}' already exists.")
        except Exception as e:
            self.logger.error(f"Error creating replication slot: {e}")
            raise

    def start_replication(self):
        try:
            self.cursor.start_replication(slot_name=self.slot_name)
            self.logger.info("Started replication.")
        except Exception as e:
            self.logger.error(f"Error starting replication: {e}")
            raise

    def consume_changes(self):
        def consume(message):
            try:
                payload_str = message.payload.decode('utf-8').strip() if isinstance(message.payload, bytes) else message.payload.strip()
                if not payload_str or payload_str.startswith(("BEGIN", "COMMIT")):
                    self.logger.info(f"System message received: {payload_str}, skipping.")
                    return

                change_data = self.parse_change_data(payload_str)
                table_name = change_data.get('table')
                if table_name:
                    self.logger.info(f"Change detected in table: {table_name}. Scheduling backup.")
                    self.backup_incrementally(table_name, changed_rows=None)
                    self._save_last_processed_state(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

                message.cursor.send_feedback()
            except Exception as e:
                self.logger.error(f"Error processing message: {e}")

        self.logger.info("Listening for changes...")
        try:
            self.cursor.start_replication(slot_name=self.slot_name, decode=True)
            self.cursor.consume_stream(consume)
        except psycopg2.errors.QueryCanceled:
            self.logger.info("Replication stream was canceled.")
        except Exception as e:
            self.logger.error(f"Error consuming replication stream: {e}")
        finally:
            self.logger.info("Replication stream closed.")

    def parse_change_data(self, payload_str):
        change_data = {}
        try:
            parts = payload_str.split(':')
            table_info = parts[0].strip().split()
            operation = parts[1].strip()
            table_name = table_info[1]
            change_data['table'] = table_name
            change_data['operation'] = operation

            column_data = parts[2].strip().split(' ')
            values = {col.split('[')[0]: col.split('[')[1].split(']')[0] for col in column_data if '[' in col}
            change_data['values'] = values
        except Exception as e:
            self.logger.error(f"Error parsing change data: {e}")
        return change_data

    def restart_replication(self):
        self.logger.info("Restarting replication stream...")
        self.start_replication()

def main():
    slot_name = "vstatetest_slot"
    output_plugin = "pgoutput"
    backup_dir = "D:\\cdc\\services\\backup"
    state_file = "last_processed_state.json"

    processor = CDCProcessor(slot_name, output_plugin, backup_dir, state_file)
    try:
        processor.create_replication_slot()
    except psycopg2.errors.DuplicateObject:
        processor.logger.info("Using existing replication slot.")

    processor.consume_changes()

if __name__ == "__main__":
    main()

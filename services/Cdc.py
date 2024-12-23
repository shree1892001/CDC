import logging
import json
import os
from datetime import datetime
import psycopg2.errors
from utils.ApplicationConnection import ApplicationConnection

class CDCProcessor:

    def __init__(self, slot_name, output_plugin, backup_dir):
        self.slot_name = slot_name
        self.output_plugin = output_plugin
        self.backup_dir = backup_dir
        self.logger = self._configure_logger()
        self.db_connection = ApplicationConnection()
        self.cursor = self.db_connection.mycursor

        os.makedirs(self.backup_dir, exist_ok=True)

    def _configure_logger(self):
        logger = logging.getLogger("CDC_Logger")
        logger.setLevel(logging.INFO)

        file_handler = logging.FileHandler("cdc_changes.log")
        file_handler.setLevel(logging.INFO)

        formatter = logging.Formatter('%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        file_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        return logger

    def _make_json_serializable(self, obj):
        """Recursively convert non-serializable types like bytes to serializable formats."""
        if isinstance(obj, bytes):
            return obj.decode("utf-8")
        elif isinstance(obj, dict):
            return {key: self._make_json_serializable(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._make_json_serializable(element) for element in obj]
        return obj

    def backup_change(self, change_data):
        """Save change data to a backup file."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = os.path.join(self.backup_dir, f"cdc_backup_{timestamp}.json")

        try:

            serializable_data = self._make_json_serializable(change_data)

            with open(backup_file, 'w') as file:
                json.dump(serializable_data, file, indent=4)
            self.logger.info(f"Backup saved to {backup_file}")
        except Exception as e:
            self.logger.error(f"Error saving backup: {e}")

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
                change_data = message.payload
                self.logger.info(f"Received change: {change_data}")
                self.backup_change(change_data)
                message.cursor.send_feedback()
            except Exception as e:
                self.logger.error(f"Error processing message: {e}")

        self.logger.info("Starting to consume changes...")
        try:
            self.cursor.consume_stream(consume)
        except Exception as e:
            self.logger.error(f"Error consuming stream: {e}")
            raise
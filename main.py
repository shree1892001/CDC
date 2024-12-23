from services.Cdc import CDCProcessor

if __name__ == "__main__":
    slot_name = "vstatetest_slot"
    output_plugin = "test_decoding"
    backup_dir="cdc_backup.json"

    cdc_processor = CDCProcessor(slot_name, output_plugin,backup_dir)

    try:
        cdc_processor.create_replication_slot()
        cdc_processor.start_replication()
        cdc_processor.consume_changes()
    except Exception as e:
        cdc_processor.logger.error(f"Unexpected error: {e}")


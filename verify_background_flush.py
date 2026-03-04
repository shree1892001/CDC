
import time
import threading
from services.CDCProcessorPITR import CDCProcessor
from services.pitr_config import DB_CONFIG
from utils.ApplicationConnection import ApplicationConnection
import os

def simulate_activity():
    """Simulate a single insert and then stop"""
    time.sleep(5)  # Wait for processor to start and settle
    print("[Test] Simulating database insert...")
    
    app_conn = ApplicationConnection()
    conn = app_conn.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO cdc_test (data) VALUES ('background_flush_test_3')")
            conn.commit()
            print("[Test] Insert committed.")
    finally:
        pass

def main():
    print("Verification: Background Flush Thread")
    print("-" * 40)
    
    # Initialize processor with a UNIQUE slot to avoid conflicts
    cdc = CDCProcessor(slot_name='verify_flush_slot')
    
    # Start simulation in thread
    sim_thread = threading.Thread(target=simulate_activity)
    sim_thread.daemon = True
    sim_thread.start()
    
    print("[Test] Running CDC with slot 'verify_flush_slot' (Wait ~25s)...")
    
    # We'll use a timeout to stop automatically
    timer = threading.Timer(25, lambda: os._exit(0))
    timer.start()
    
    try:
        cdc.create_replication_slot()
        cdc.start_replication()
        cdc.consume_changes()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        cdc._shutdown()

if __name__ == "__main__":
    main()

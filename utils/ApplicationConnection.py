import psycopg2
from psycopg2.extras import LogicalReplicationConnection
from threading import Lock
from Common.constants import *

class ApplicationConnection:
    _instance = None
    _lock = Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if not cls._instance:
                cls._instance = super(ApplicationConnection, cls).__new__(cls)
        return cls._instance

    def __init__(self, dbname=None, host=None, user=None, password=None):
        if not hasattr(self, "_initialized"):
            self.dbname = dbname or DB_NAME
            self.host = host or DB_HOST
            self.user = user or DB_USER
            self.password = password or DB_PASS
            self._connection = None
            self._replication_connection = None
            self._initialized = True

    def connect(self, replication=False):
        """
        Get database connection
        
        Args:
            replication: If True, returns a replication connection
        
        Returns:
            Database connection
        """
        if replication:
            if self._replication_connection is None or self._replication_connection.closed:
                try:
                    self._replication_connection = psycopg2.connect(
                        f"dbname='{self.dbname}' host='{self.host}' user='{self.user}' password='{self.password}'",
                        connection_factory=LogicalReplicationConnection
                    )
                except Exception as e:
                    raise Exception(f"Error connecting to the database: {e}")
            return self._replication_connection
        else:
            if self._connection is None or self._connection.closed:
                try:
                    self._connection = psycopg2.connect(
                        f"dbname='{self.dbname}' host='{self.host}' user='{self.user}' password='{self.password}'"
                    )
                except Exception as e:
                    raise Exception(f"Error connecting to the database: {e}")
            return self._connection
    
    @property
    def mycursor(self):
        """Get cursor for replication connection"""
        conn = self.connect(replication=True)
        return conn.cursor()
    
    def close(self):
        """Close all connections"""
        if self._connection and not self._connection.closed:
            self._connection.close()
        if self._replication_connection and not self._replication_connection.closed:
            self._replication_connection.close()

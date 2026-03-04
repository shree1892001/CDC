import sys
sys.path.insert(0, r'd:\CDC')
try:
    from services import PITRBackupManager
    print('IMPORT_OK')
except Exception as e:
    print('IMPORT_FAIL', repr(e))

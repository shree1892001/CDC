
import re

def _parse_column_data(data_str):
    data = {}
    
    # Split by spaces, but handle quoted values
    pattern = r"(\w+)\[([^\]]+)\]:('(?:[^']|'')*'|[^\s]+)"
    matches = re.findall(pattern, data_str)
    
    for col_name, col_type, col_value in matches:
        # Remove quotes from string values
        if col_value.startswith("'") and col_value.endswith("'"):
            col_value = col_value[1:-1].replace("''", "'")
        
        # Convert to appropriate type
        if col_value == 'null':
            col_value = None
        elif col_type in ('integer', 'bigint', 'smallint'):
            col_value = int(col_value) if col_value else None
        elif col_type in ('numeric', 'decimal', 'real', 'double precision'):
            col_value = float(col_value) if col_value else None
        elif col_type == 'boolean':
            col_value = col_value.lower() == 'true' if col_value else None
        
        data[col_name] = col_value
    
    return data

def parse_payload(payload):
    parts = payload.split(':', 2)
    if len(parts) < 3:
        return None
        
    table_part = parts[0].strip()
    operation = parts[1].strip()
    data_part = parts[2].strip()
    
    print(f"Operation: {operation}")
    print(f"Data Part: {data_part}")
    
    data = _parse_column_data(data_part)
    return data

# Test cases
print("--- Case 1: Standard INSERT ---")
payload1 = "table public.users: INSERT: id[integer]:1 name[text]:'John'"
data1 = parse_payload(payload1)
print(f"Result: {data1}\n")

print("--- Case 2: UPDATE (Default Identity - only new values usually, unless PK changed) ---")
payload2 = "table public.users: UPDATE: id[integer]:1 name[text]:'Jane'"
data2 = parse_payload(payload2)
print(f"Result: {data2}\n")

print("--- Case 3: UPDATE (Replica Identity FULL - with old-key) ---")
# Simulating what test_decoding might output for detailed update
# Note: logical decoding output format for updates with options can vary, 
# but typically: "old-key: col[type]:val ... new-tuple: col[type]:val ..."
payload3 = "table public.users: UPDATE: old-key: id[integer]:1 name[text]:'John' new-tuple: id[integer]:1 name[text]:'Jane'"
data3 = parse_payload(payload3)
print(f"Result: {data3}")
# Expected: data3 should ideally separate old and new. 
# Actual prediction: It will merge them, with 'Jane' overwriting 'John' for name. 
# old_data will be lost.

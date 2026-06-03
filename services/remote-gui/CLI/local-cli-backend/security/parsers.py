# parsers.py
import re
import json

def parse_table_fixed(text: str) -> list:
    lines = text.strip().splitlines()

    lines = text.strip().splitlines()
    if len(lines) < 2:
        print("Not enough lines for a table.")
        return []

    separator_index = 0
    for i, row in enumerate(lines):
        if row and ('|' in row or '---' in row):
            separator_index = i
            break
    
    if separator_index > 0:
        lines = lines[separator_index-1:]

    # print("Lines", lines)
    # print("Separator Index", separator_index)
    
    # Get the header and separator rows
    header_line = lines[0]
    separator_line = lines[1]

    # print("Header Line", header_line)
    # print("Separator Line", separator_line)

    try:
        cutoff_index = lines.index('')
        lines = lines[:cutoff_index]
    except ValueError:
        pass  # No empty line found, proceed with the original lines

    # print("lines", lines)

    boundaries = [i for i, ch in enumerate(separator_line) if ch == ' ']

    if boundaries and boundaries[0] != 0:
        boundaries = [0] + boundaries
    else:
        boundaries = [0] + boundaries

    split_boundaries = [len(i.strip())+1 for i in separator_line.split(' ')]
    split_boundaries.insert(0, 0)
    split_boundaries = [sum(split_boundaries[:i+1]) for i in range(len(split_boundaries))]
    split_boundaries.pop()

    headers = []
    for i in range(len(split_boundaries) - 1):
        start = split_boundaries[i]
        end = split_boundaries[i+1]
        new_header = header_line[start:end]
        headers.append(new_header.strip())


    # Remove any empty header entries (if any)
    headers = [h for h in headers if h]

    print("Headers", headers)

    data = []
    for row in lines[2:]:
        parts = []
        for i in range(len(split_boundaries) - 1):
            start = split_boundaries[i]
            end = split_boundaries[i+1]
            new_row_item = row[start:end]
            parts.append(new_row_item.strip())

        if len(parts) == len(headers):
            new_row = dict(zip(headers, parts))
            data.append(new_row)
    return data



def parse_table(text: str) -> list:
    """
    Parse a table-formatted text into a list of dictionaries.
    This approach uses the positions of the pipe characters in the separator row
    to determine column boundaries, and then slices the header and data rows accordingly.
    """
    lines = text.strip().splitlines()
    if len(lines) < 2:
        print("Not enough lines for a table.")
        return []

    separator_index = 0
    for i, row in enumerate(lines):
        if '|' in row or '---' in row:
            separator_index = i
            break
    
    if separator_index > 0:
        lines = lines[separator_index-1:]

    print("Lines", lines)
    print("Separator Index", separator_index)
    
    # Get the header and separator rows
    header_line = lines[0]
    separator_line = lines[1]
    
    # Find the positions of the pipe characters in the separator line.
    # These indices will be used as boundaries.
    boundaries = [i for i, ch in enumerate(separator_line) if ch == '|']
    # Also include the start (0) if not already there.
    if boundaries and boundaries[0] != 0:
        boundaries = [0] + boundaries
    else:
        boundaries = [0] + boundaries

    split_boundaries = [len(i.strip())+1 for i in separator_line.split('|')]
    split_boundaries.insert(0, 0)
    split_boundaries = [sum(split_boundaries[:i+1]) for i in range(len(split_boundaries))]
    split_boundaries.pop()

    headers = []
    for i in range(len(split_boundaries) - 1):
        start = split_boundaries[i]
        end = split_boundaries[i+1]
        new_header = header_line[start:end]
        headers.append(new_header.strip())


    # Remove any empty header entries (if any)
    headers = [h for h in headers if h]
    
    data = []
    for line in lines[2:]:
        # print(line)
        # Skip if line is a separator line or empty
        if set(line.strip()) in [{'|'}]:
            continue
        # Remove borders if present and then split
        parts = [p.strip() for p in line.split('|')]
        parts.pop()
        if len(parts) == len(headers):
            row = dict(zip(headers, parts))
            data.append(row)
    return data



def parse_json(text: str) -> dict:
    """
    Parse JSON text into a dictionary.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}

def parse_response(raw: str) -> dict:
    """
    Unified response parser.
    Checks if the response is JSON, table formatted, or a simple string,
    and returns a standardized JSON structure.
    """

    # Check if text resembles a table (e.g., has headers and delimiters)

    if isinstance(raw, dict) and 'blobs' in raw:
        return {"type": "blobs", "data": raw['blobs']['Query']}
        # return {"type": "table", "data": raw['blobs']['Query']}

    if isinstance(raw, bool):
        return {"type": "string", "data": str(raw).lower()}

    if '|' in raw:
        print("FOUND TABLE")
        table_data = parse_table(raw)
        if table_data:
            return {"type": "table", "data": table_data}
    elif '---' in raw:
        print("FOUND FIXED TABLE NO | DELIMITERS")
        table_data = parse_table_fixed(raw)
        if table_data:
            return {"type": "table", "data": table_data}
        
    if type(raw) is list:
        return {"type": "json", "data": raw}
    
    if type(raw) is dict:
        return {"type": "json", "data": raw}
        
    # Try to parse as JSON first
    # parsed = parse_json(raw_text)
    # if parsed:
    #     return {"type": "json", "data": parsed}
    
    # Otherwise, treat it as a simple message
    return {"type": "string", "data": raw.strip()}




    


# raw = '\r\n    Process         Status       Details                                                                     \r\n    ---------------|------------|---------------------------------------------------------------------------|\r\n    TCP            |Running     |Listening on: 10.10.1.31:32348, Threads Pool: 6                            |\r\n    REST           |Running     |Listening on: 23.239.12.151:32349, Threads Pool: 5, Timeout: 20, SSL: False|\r\n    Operator       |Not declared|                                                                           |\r\n    Blockchain Sync|Running     |Sync every 30 seconds with master using: 10.10.1.10:32048                  |\r\n    Scheduler      |Running     |Schedulers IDs in use: [0 (system)] [1 (user)]                             |\r\n    Blobs Archiver |Not declared|                                                                           |\r\n    MQTT           |Not declared|                                                                           |\r\n    Message Broker |Not declared|No active connection                                                       |\r\n    SMTP           |Not declared|                                                                           |\r\n    Streamer       |Not declared|                                                                           |\r\n    Query Pool     |Running     |Threads Pool: 3                                                            |\r\n    Kafka Consumer |Not declared|                                                                           |\r\n    gRPC           |Not declared|                                                                           |\r\n    OPC-UA Client  |Not declared|                                                                           |\r\n    Publisher      |Not declared|                                                                           |\r\n    Distributor    |Not declared|                                                                           |\r\n    Consumer       |Not declared|                                                                           |\r\n'

# if __name__ == "__main__":
#     print("Testing parse_table")
#     table_result = parse_response(raw)
#     print("Parsed Table Result:", table_result)
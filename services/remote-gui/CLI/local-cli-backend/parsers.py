# parsers.py
import json

def parse_table_fixed(text: str) -> list:
    lines = text.strip().splitlines()

    lines = text.strip().splitlines()
    if len(lines) < 2:
        print("Not enough lines for a table.")
        return []

    # Split lines into a list of lists, splitting where the item is ''
    split_lines = []
    current_split = []
    for line in lines:
        if line.strip() == '':
            if current_split:
                split_lines.append(current_split)
                current_split = []
        else:
            current_split.append(line)
    if current_split:
        split_lines.append(current_split)
        

    # For each list in split_lines, check for a table unit and combine lines after the top two rows.
    # Keep the top two rows for the first table unit.
    table_units = []
    additional_info = []
    top_added = False
    for sublines in split_lines:
        # Check if this unit contains '---' or '|', i.e. it's a table
        if any(('---' in line or '|' in line) for line in sublines):
            if not top_added:
                # For the first table unit, keep the top two rows
                if len(sublines) >= 2:
                    table_units.extend(sublines[:2])   # header + separator
                    table_units.extend(sublines[2:])   # the rest (body)
                else:
                    table_units.extend(sublines)       # not enough lines, just extend
                top_added = True
            else:
                # For subsequent table units, only keep body rows (after first two lines)
                if len(sublines) > 2:
                    table_units.extend(sublines[2:])
        else:
            # Not a table unit, add to additional_info
            additional_info.extend(sublines)
    print("Combined and normalized table unit lines:", table_units)
    # try:
    #     additional_info = json.loads(' '.join([item.strip() for item in additional_info]))
    # except Exception:
    additional_info = ' '.join([item.strip() for item in additional_info])
    print("Additional Info:", additional_info)

    lines = table_units

    separator_index = 0
    for i, row in enumerate(lines):
        if row and ('|' in row or '---' in row):
            separator_index = i
            break
    
    if separator_index > 0:
        lines = lines[separator_index-1:]

    print("Lines", lines)
    print("Separator Index", separator_index)
    
    # Get the header and separator rows
    header_line = lines[0]
    separator_line = lines[1]

    print("Header Line", header_line)
    print("Separator Line", separator_line)

    try:
        cutoff_index = lines.index('')
        lines = lines[:cutoff_index]
    except ValueError:
        pass  # No empty line found, proceed with the original lines

    print("lines", lines)

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
    return {"data": data, "additional_info": additional_info}



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
    try:
        print(f"=== PARSING RESPONSE ===")
        print(f"Raw response type: {type(raw)}")
        print(f"Raw response length: {len(str(raw)) if raw else 0}")
        print(f"Raw response preview: {str(raw)[:500] if raw else 'None'}...")
        print(f"=== END PARSING RESPONSE ===")
    except Exception as e:
        print(f"Error in parse_response debugging: {e}")

    try:
        # Check if text resembles a table (e.g., has headers and delimiters)

        if isinstance(raw, dict) and 'blobs' in raw:
            print("raw blobs:", raw)
            return {"type": "blobs", "data": raw['blobs']['Query']}
            # return {"type": "table", "data": raw['blobs']['Query']}

        if isinstance(raw, dict) and 'streaming' in raw:
            print("raw streaming:", raw)
            # For streaming, the data structure might be different than blobs
            streaming_data = raw['streaming']
            # Check if it has the same structure as blobs
            if isinstance(streaming_data, dict) and 'Query' in streaming_data:
                return {"type": "streaming", "data": streaming_data['Query']}
            else:
                # If it's direct data, use it as is
                return {"type": "streaming", "data": streaming_data}
        
        if isinstance(raw, bool):
            return {"type": "string", "data": str(raw).lower()}

        if '|' in raw:
            print("FOUND TABLE")
            table_data = parse_table(raw)
            if table_data:
                return {"type": "table", "data": table_data}
        elif '---' in raw:
            print("FOUND FIXED TABLE NO | DELIMITERS")
            table_result = parse_table_fixed(raw)
            if table_result and table_result.get("data"):
                result = {"type": "table", "data": table_result["data"]}
                if table_result.get("additional_info"):
                    result["additional_content"] = table_result["additional_info"]
                return result
            
        if type(raw) is list:
            return {"type": "json", "data": raw}
        
        if type(raw) is dict:
            return {"type": "json", "data": raw}
            
        # Try to parse as JSON first
        # parsed = parse_json(raw_text)
        # if parsed:
        #     return {"type": "json", "data": parsed}
        
        if isinstance(raw, str):
            # Replace \r\n with \n and normalize line endings
            raw = raw.replace('\r\n', '\n').replace('\r', '\n')
            # Remove leading/trailing whitespace
            raw = raw.strip()
            
        # Otherwise, treat it as a simple message
        return {"type": "string", "data": raw}
    
    except Exception as e:
        print(f"=== PARSE_RESPONSE ERROR ===")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {str(e)}")
        print(f"Raw data type: {type(raw)}")
        print(f"Raw data: {str(raw)[:1000] if raw else 'None'}")
        print(f"=== END PARSE_RESPONSE ERROR ===")
        
        return {
            "type": "error",
            "data": f"Error parsing response: {str(e)}",
            "error_details": {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "raw_data_type": str(type(raw)),
                "raw_data_preview": str(raw)[:500] if raw else 'None'
            }
        }




    


# raw = '\r\n    Process         Status       Details                                                                     \r\n    ---------------|------------|---------------------------------------------------------------------------|\r\n    TCP            |Running     |Listening on: 10.10.1.31:32348, Threads Pool: 6                            |\r\n    REST           |Running     |Listening on: 23.239.12.151:32349, Threads Pool: 5, Timeout: 20, SSL: False|\r\n    Operator       |Not declared|                                                                           |\r\n    Blockchain Sync|Running     |Sync every 30 seconds with master using: 10.10.1.10:32048                  |\r\n    Scheduler      |Running     |Schedulers IDs in use: [0 (system)] [1 (user)]                             |\r\n    Blobs Archiver |Not declared|                                                                           |\r\n    MQTT           |Not declared|                                                                           |\r\n    Message Broker |Not declared|No active connection                                                       |\r\n    SMTP           |Not declared|                                                                           |\r\n    Streamer       |Not declared|                                                                           |\r\n    Query Pool     |Running     |Threads Pool: 3                                                            |\r\n    Kafka Consumer |Not declared|                                                                           |\r\n    gRPC           |Not declared|                                                                           |\r\n    OPC-UA Client  |Not declared|                                                                           |\r\n    Publisher      |Not declared|                                                                           |\r\n    Distributor    |Not declared|                                                                           |\r\n    Consumer       |Not declared|                                                                           |\r\n'

# if __name__ == "__main__":
#     print("Testing parse_table")
#     table_result = parse_response(raw)
#     print("Parsed Table Result:", table_result)
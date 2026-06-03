#!/usr/bin/env python3
"""
Power Monitoring Report Generator
Generates Excel and PDF reports from AnyLog power meter and tap position data.

Usage:
    python generate_power_report.py

Requirements:
    pip install pandas openpyxl pillow reportlab

For PDF conversion, LibreOffice must be installed:
    libreoffice --headless --convert-to pdf --outdir <output_dir> <excel_file>
"""

# Try to import pandas - handle numpy compatibility issues
try:
    import pandas as pd
    HAS_PANDAS = True
except (ImportError, AttributeError) as e:
    HAS_PANDAS = False
    pd = None
    print(f"⚠️  Could not import pandas (numpy compatibility issue?): {e}")
    print("   Try: pip install --upgrade numpy>=2.0.0 pandas>=2.2.0")

# Try to import openpyxl
try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, Border, Side, PatternFill
    from openpyxl.worksheet.page import PageMargins
    from openpyxl.drawing.image import Image
    HAS_OPENPYXL = True
except (ImportError, AttributeError) as e:
    HAS_OPENPYXL = False
    print(f"⚠️  Could not import openpyxl: {e}")

from datetime import datetime, timedelta
import subprocess
import requests
import os
import json
import re


# Try to import yaml, but make it optional
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Image as RLImage, Paragraph, Spacer, PageBreak
from reportlab.lib.pagesizes import landscape, letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib import colors
from reportlab.lib.units import inch


def _get_data(conn: str, command: str, destination: str = None, timeout: int = 60):
    headers = {
        "command": command,
        "User-Agent": "AnyLog/1.23"
    }
    if destination:
        headers["destination"] = destination

    try:
        response = requests.get(url=f"http://{conn}", headers=headers, timeout=timeout)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        raise Exception(f"Request timeout after {timeout} seconds while executing command: {command}")
    except requests.exceptions.RequestException as error:
        raise Exception(f"Request failed: {str(error)}")
    except Exception as error:
        raise Exception(f"Unexpected error: {str(error)}")
    return response


def _update_timestamp(end_time) -> str:
    # update end timestamp
    end_time = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
    end_time += timedelta(hours=1)
    end_time = end_time.strftime("%Y-%m-%d %H:%M:%S")
    return end_time


def image_download(image_url):
    """Download image from URL or return local file path"""
    image_url_path = os.path.expandvars(os.path.expanduser(image_url))
    
    # If it's already a local file, return it
    if os.path.isfile(image_url_path):
        return image_url_path
    
    # Try to download from URL
    try:
        import tempfile
        # Create a temporary file with proper extension
        temp_dir = tempfile.gettempdir()
        temp_file = os.path.join(temp_dir, f"report_logo_{hash(image_url) % 10000}.png")
        
        # Download the image
        response = requests.get(image_url_path, timeout=10)
        response.raise_for_status()
        
        with open(temp_file, 'wb') as f:
            f.write(response.content)
        
        return temp_file
    except Exception:
        # Return None instead of raising, so report can still be generated
        return None


def load_config(config_path: str = None, config_data: dict = None):
    """
    Load configuration from file or dict.
    Returns default config if neither is provided.
    """
    if config_data:
        return config_data
    
    if config_path:
        config_path = os.path.expandvars(os.path.expanduser(config_path))
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                if (config_path.endswith('.yaml') or config_path.endswith('.yml')):
                    if HAS_YAML:
                        return yaml.safe_load(f)
                    else:
                        raise Exception("YAML support not available. Install PyYAML: pip install pyyaml")
                else:
                    return json.load(f)
    
    # Return default config
    default_config_path = os.path.join(
        os.path.dirname(__file__),
        'templates',
        'report_config_template.json'
    )
    if os.path.exists(default_config_path):
        with open(default_config_path, 'r') as f:
            return json.load(f)
    
    # Fallback to hardcoded defaults
    return {
        "db_name": "cos",
        "title": "CITY OF SABETHA MUNICIPAL POWER PLANT",
        "subtitle": "EVERGY INTERCONNECTION",
        "logo_url": "https://tse1.mm.bing.net/th/id/OIP.7bJT74xSx81aYJgz-rl-TwAAAA?cb=ucfimg2&ucfimg=1&rs=1&pid=ImgDetMain&o=7&rm=3",
        "queries": {
            "power_plant": "SELECT increments({increment_unit}, {increment_value}, {time_column}), monitor_id, MIN(timestamp)::ljust(19) AS min_ts, MAX(timestamp)::ljust(19) AS max_ts, AVG(realpower) AS kw, AVG(a_n_voltage) AS a_kv, AVG(b_n_voltage) AS b_kv, AVG(c_n_voltage) AS c_kv, AVG(powerfactor) AS pf, AVG(a_current) AS amp_1, AVG(b_current) AS amp_2, AVG(c_current) AS amp_3, AVG(frequency) AS hz FROM pp_pm WHERE {time_column} >= '{start_time}' AND {time_column} < '{end_time}' AND monitor_id='{monitor_id}' GROUP BY monitor_id ORDER BY min_ts",
            "tap_value": "SELECT increments({increment_unit}, {increment_value}, {time_column}), monitor_id, MIN(timestamp)::ljust(19) AS min_ts, MAX(timestamp)::ljust(19) AS max_ts, AVG(value) AS tap FROM pv WHERE {time_column} >= '{start_time}' AND {time_column} < '{end_time}' GROUP BY monitor_id ORDER BY min_ts"
        },
        "data_merging": {
            "primary_query": "power_plant",
            "join_key": "hour",
            "join_method": "left",
            "timestamp_field": "min_ts",
            "timestamp_floor": "h"
        },
        "table_columns": {
            "column_definitions": [
                {"name": "DATE/TIME", "source": "min_ts", "source_query": "power_plant", "transform": "datetime", "format": "datetime"},
                {"name": "kW", "source": "kw", "source_query": "power_plant", "transform": "round", "format": "int"},
                {"name": "KV", "source": ["a_kv", "b_kv", "c_kv"], "source_query": "power_plant", "transform": "average", "format": "int"},
                {"name": "PF", "source": "pf", "source_query": "power_plant", "transform": "divide", "transform_value": 100, "format": "float", "decimal_places": 2},
                {"name": "1", "source": "amp_1", "source_query": "power_plant", "transform": "round", "format": "int"},
                {"name": "2", "source": "amp_2", "source_query": "power_plant", "transform": "round", "format": "int"},
                {"name": "3", "source": "amp_3", "source_query": "power_plant", "transform": "round", "format": "int"},
                {"name": "1", "source": "a_kv", "source_query": "power_plant", "transform": "divide", "transform_value": 100, "format": "float", "decimal_places": 2},
                {"name": "2", "source": "b_kv", "source_query": "power_plant", "transform": "divide", "transform_value": 100, "format": "float", "decimal_places": 2},
                {"name": "3", "source": "c_kv", "source_query": "power_plant", "transform": "divide", "transform_value": 100, "format": "float", "decimal_places": 2},
                {"name": "Hz", "source": "hz", "source_query": "power_plant", "transform": "divide", "transform_value": 100, "format": "float", "decimal_places": 2},
                {"name": "TAP", "source": "tap", "source_query": "tap_value", "transform": "round", "format": "int", "allow_null": True}
            ],
            "column_groups": {"AMPS": [4, 5, 6], "VOLTAGE": [7, 8, 9]},
            "column_widths": {
                "portrait": [80, 35, 35, 30, 30, 30, 30, 35, 35, 35, 30, 30],
                "landscape": [120, 50, 50, 40, 50, 50, 50, 50, 50, 50, 40, 40]
            }
        }
    }


# Validate database and tables
def check_data(conn: str, dbms: str):
    command = f"get data nodes where dbms={dbms} and table=%s and format=json"
    is_tables = True
    for table in ["pp_pm", "pv"]:
        response = _get_data(conn=conn, command=command % table)
        if not response.json():
            is_tables = False
    return is_tables


# monitor_ids
def get_monitor_ids(conn: str, dbms: str):
    output = []
    query = "SELECT distinct(monitor_id) AS monitor_id FROM pp_pm WHERE period(hour, 1, now(), timestamp)"
    command = f"sql {dbms} format=json and stat=false {query}"
    response = _get_data(conn=conn, command=command, destination="network")
    try:
        for monitor_id in response.json()['Query']:
            output.append(monitor_id['monitor_id'])
    except Exception as error:
        raise Exception(error)
    return output


# Execute query from config with placeholders
def execute_config_query(conn: str, dbms: str, query_template: str, 
                         increment_unit: str, increment_value: int, time_column: str,
                         start_time: str, end_time: str, monitor_id: str = None):
    """
    Execute a query from config with placeholders replaced.
    Placeholders: {increment_unit}, {increment_value}, {time_column}, 
                  {start_time}, {end_time}, {monitor_id}
    """
    query = query_template.format(
        increment_unit=increment_unit,
        increment_value=increment_value,
        time_column=time_column,
        start_time=start_time,
        end_time=end_time,
        monitor_id=monitor_id if monitor_id else ''
    )
    
    command = f"sql {dbms} format=json and stat=false {query.replace(chr(10), ' ').replace(chr(13), ' ').strip()}"
    response = _get_data(conn=conn, command=command, destination="network")
    try:
        return response.json()['Query']
    except Exception as error:
        raise Exception(error)


# Power meter data from AnyLog query (legacy function for backward compatibility):
def select_power_plant(conn: str, dbms: str, increment_unit: str, increment_value: int, time_column: str,
                       start_time: str, end_time: str, monitor_id: str):
    query = """
    SELECT 
        increments({increment_unit}, {increment_value}, {time_column}), monitor_id, MIN(timestamp)::ljust(19) AS min_ts, 
        MAX(timestamp)::ljust(19) AS max_ts, AVG(realpower) AS kw, AVG(a_n_voltage) AS a_kv, 
        AVG(b_n_voltage) AS b_kv, AVG(c_n_voltage) AS c_kv, AVG(powerfactor) AS pf, 
        AVG(a_current) AS amp_1, AVG(b_current) AS amp_2, AVG(c_current) AS amp_3, 
        AVG(frequency) AS hz
    FROM 
        pp_pm 
    WHERE
        {time_column} >= '{start_time}' AND 
        {time_column} < '{end_time}' AND 
        monitor_id='{monitor_id}' 
    GROUP BY 
        monitor_id 
    ORDER BY 
        min_ts
    """
    return execute_config_query(conn, dbms, query, increment_unit, increment_value, 
                                time_column, start_time, end_time, monitor_id)


# PV meter data from AnyLog query (legacy function for backward compatibility):
def select_tap_value(conn: str, dbms: str, increment_unit: str, increment_value: int, time_column: str, start_time: str,
                     end_time: str):
    query = """
    SELECT 
        increments({increment_unit}, {increment_value}, {time_column}), monitor_id, MIN(timestamp)::ljust(19) AS min_ts, 
        MAX(timestamp)::ljust(19) AS max_ts, AVG(value) AS tap
    FROM 
        pv 
    WHERE 
        {time_column} >= '{start_time}' AND {time_column} < '{end_time}'
    GROUP BY 
        monitor_id 
    ORDER BY 
        min_ts
    """
    return execute_config_query(conn, dbms, query, increment_unit, increment_value, 
                                time_column, start_time, end_time)




def _draw_page_number(canvas, doc):
    """Draw page number at bottom center on first page"""
    canvas.setFont("Helvetica", 9)
    page_text = f"Page {doc.page}"
    page_width = canvas.stringWidth(page_text, "Helvetica", 9)
    canvas.drawString((doc.pagesize[0] - page_width) / 2, 20, page_text)

def _draw_later_pages(canvas, doc, config):
    """Draw header on later pages: timestamp and page number at bottom"""
    now = datetime.now()
    timestamp = f"{now.month}/{now.day}/{now.year} {now.strftime('%H:%M:%S')}"
    
    # Draw timestamp at top left
    canvas.setFont("Helvetica", 9)
    canvas.drawString(20, doc.pagesize[1] - 20, timestamp)
    
    # Draw page number at bottom center
    page_text = f"Page {doc.page}"
    page_width = canvas.stringWidth(page_text, "Helvetica", 9)
    canvas.drawString((doc.pagesize[0] - page_width) / 2, 20, page_text)


def generate_report(merged_df, config, report_config=None, page_orientation='landscape'):
    """
    Generate the Power Monitoring PDF report.
    
    Args:
        merged_df: DataFrame with merged data
        config: Runtime config (output_dir, output_filename, logo_path, etc.)
        report_config: Report configuration from JSON/YAML file
        page_orientation: 'landscape' or 'portrait'
    """
    # Load report config if not provided
    if report_config is None:
        report_config = load_config()
    
    pdf_path = os.path.join(config['output_dir'], f"{config['output_filename']}.pdf")
    
    # Set page size based on orientation
    if page_orientation == 'portrait':
        pagesize = letter
    else:
        pagesize = landscape(letter)
    
    # Calculate available width (page width minus margins)
    page_width = pagesize[0]
    available_width = page_width - 40  # 20px margin on each side
    
    # Create document with callbacks for page numbers
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=pagesize,
        leftMargin=20, rightMargin=20, topMargin=20, bottomMargin=20,
        onFirstPage=lambda canvas, doc: _draw_page_number(canvas, doc),
        onLaterPages=lambda canvas, doc: _draw_later_pages(canvas, doc, config)
    )

    elements = []
    styles = getSampleStyleSheet()
    
    # Create centered style for subtitle
    centered_style = ParagraphStyle(
        'Centered',
        parent=styles['Normal'],
        alignment=TA_CENTER,

        fontSize=11,
        spaceAfter=8
    )

    # Create custom title style
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=13,
        alignment=TA_CENTER,
        spaceAfter=6
    )

    # Timestamp and Logo on same line
    now = datetime.now()
    timestamp = f"{now.month}/{now.day}/{now.year} {now.strftime('%H:%M:%S')}"
    
    # Get title and subtitle from config
    config_id = report_config.get('id')
    title = report_config.get('title', '') if report_config else ''
    subtitle = report_config.get('subtitle', '') if report_config else ''
    logo_path = config.get("logo_path") if config else None

    # Create header table with timestamp (left) and logo (right)
    # Adjust column widths based on available space
    logo_width = 50
    timestamp_col_width = available_width - logo_width - 10  # Leave some gap
    
    if logo_path and os.path.exists(str(logo_path)):
        try:
            logo = RLImage(logo_path)
            logo.drawHeight = 40
            logo.drawWidth = 40
            
            # Create a table to align timestamp (left) and logo (right)
            # Use available width dynamically
            header_table = Table([[Paragraph(timestamp, styles["Normal"]), logo]], 
                               colWidths=[timestamp_col_width, logo_width])
            header_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            elements.append(header_table)
        except Exception:
            elements.append(Paragraph(timestamp, styles["Normal"]))
    else:
        elements.append(Paragraph(timestamp, styles["Normal"]))

    elements.append(Spacer(1, 8))

    # Title (centered)
    if title:
        elements.append(Paragraph(
            f"<b>{title}</b>",
            title_style
        ))

    # Subtitle (centered)
    # monitor_id = config.get('monitor_id')
    if subtitle:
        elements.append(Paragraph(
            f"<b>{subtitle}</b>",
            centered_style
        ))
    
    # Add spacing after subtitle (only if subtitle was processed)
    if subtitle:
        elements.append(Spacer(1, 6))

    # Get table configuration from config
    table_config = report_config.get('table_columns', {}) if report_config else {}
    column_definitions = table_config.get('column_definitions', [])
    
    # If using old format (power_plant array), convert to new format
    if not column_definitions and 'power_plant' in table_config:
        # Legacy format - create basic definitions
        column_names = table_config.get('power_plant', [])
        column_definitions = [{"name": name} for name in column_names]
    
    # Extract column names from definitions
    column_names = [col_def.get('name', '') for col_def in column_definitions]
    column_groups = table_config.get('column_groups', {})
    
    num_columns = len(column_names)
    
    # Data Table - Build row 0 dynamically from column_groups
    table_data = []
    
    # Row 0: Build header row with group labels
    row0 = [""] * num_columns
    for group_name, column_indices in column_groups.items():
        if column_indices and len(column_indices) > 0:
            # Set the group name in the first column of the group
            first_idx = column_indices[0]
            if first_idx < num_columns:
                row0[first_idx] = group_name
    table_data.append(row0)

    # Row 1: All column sub-headers from config
    table_data.append(column_names)

    # Data rows - build dynamically from column definitions
    for _, row in merged_df.iterrows():
        data_row = []
        
        for col_def in column_definitions:
            source = col_def.get('source')
            transform = col_def.get('transform', 'none')
            transform_value = col_def.get('transform_value')
            format_type = col_def.get('format', 'string')
            decimal_places = col_def.get('decimal_places', 2)
            allow_null = col_def.get('allow_null', False)
            
            # Get the value from the row
            if source is None:
                value = ""
            elif isinstance(source, list):
                # Multiple sources - apply transform (e.g., average)
                values = []
                for s in source:
                    if s in row.index:
                        values.append(row[s])
                valid_values = [v for v in values if pd.notna(v) and v is not None]
                if transform == 'average' and valid_values:
                    value = sum(float(v) for v in valid_values) / len(valid_values)
                elif transform == 'sum' and valid_values:
                    value = sum(float(v) for v in valid_values)
                else:
                    value = valid_values[0] if valid_values else None
            else:
                # Single source field - row is a pandas Series from iterrows()
                if source in row.index:
                    value = row[source]
                else:
                    value = None
            
            # Handle null values
            if pd.isna(value) or value is None:
                if allow_null:
                    data_row.append("")
                else:
                    data_row.append(0)
                continue
            
            # Apply transformations
            if transform == 'datetime':
                # Format datetime - this returns a string, so skip other transforms
                try:
                    ts = pd.to_datetime(value).floor("h")
                    value = f"{ts.month}/{ts.day}/{ts.year} {ts.strftime('%H:%M:%S')}"
                except Exception:
                    value = str(value)
            else:
                # Apply numeric transformations
                try:
                    if transform == 'divide' and transform_value:
                        value = float(value) / float(transform_value)
                    elif transform == 'multiply' and transform_value:
                        value = float(value) * float(transform_value)
                    elif transform == 'round':
                        value = round(float(value))
                    elif transform == 'none' or transform is None:
                        # No transform, but may need to convert to float for formatting
                        if format_type in ['int', 'float']:
                            value = float(value)
                    
                    # Apply formatting
                    if format_type == 'int':
                        value = int(round(float(value)))
                    elif format_type == 'float':
                        value = round(float(value), decimal_places)
                    elif format_type == 'string' or format_type == 'datetime':
                        value = str(value)
                except (ValueError, TypeError):
                    # If transformation fails, use original value or empty string
                    value = "" if not allow_null else value
            
            data_row.append(value)
        
        table_data.append(data_row)

    # Get column widths from config or use defaults
    column_widths_config = table_config.get('column_widths', {})
    
    if page_orientation == 'portrait':
        col_widths = column_widths_config.get('portrait', None)
        if col_widths is None:
            # Default portrait widths if not in config
            col_widths = [80, 35, 35, 30, 30, 30, 30, 35, 35, 35, 30, 30]
        table_font_size = 7
    else:
        col_widths = column_widths_config.get('landscape', None)
        if col_widths is None:
            # Default landscape widths if not in config
            col_widths = [120, 50, 50, 40, 50, 50, 50, 50, 50, 50, 40, 40]
        table_font_size = 8
    
    # Ensure column widths match number of columns
    if len(col_widths) != num_columns:
        # If mismatch, pad or truncate to match
        if len(col_widths) < num_columns:
            # Pad with average of existing widths
            avg_width = sum(col_widths) / len(col_widths) if col_widths else 40
            col_widths.extend([avg_width] * (num_columns - len(col_widths)))
        else:
            # Truncate to match
            col_widths = col_widths[:num_columns]
    
    # Normalize column widths to fit available width
    total_col_width = sum(col_widths)
    if total_col_width > available_width:
        # Scale down proportionally
        scale_factor = available_width / total_col_width
        col_widths = [w * scale_factor for w in col_widths]
    
    # Store the final table width for footer matching
    main_table_width = sum(col_widths)
    
    # Create table with calculated column widths
    table = Table(table_data, repeatRows=2, colWidths=col_widths)

    # Build table style with dynamic SPAN commands based on column_groups
    table_style_commands = [
        # Row 0: Labels spanning - gray background
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ]
    
    # Add SPAN commands for column groups
    # First, span individual columns that don't belong to groups
    spanned_columns = set()
    for group_name, column_indices in column_groups.items():
        if column_indices and len(column_indices) > 0:
            # Span the group across its columns
            first_col = min(column_indices)
            last_col = max(column_indices)
            if first_col < num_columns and last_col < num_columns:
                table_style_commands.append(("SPAN", (first_col, 0), (last_col, 0)))
                spanned_columns.update(column_indices)
    
    # Span individual columns that aren't part of groups
    for i in range(num_columns):
        if i not in spanned_columns:
            table_style_commands.append(("SPAN", (i, 0), (i, 0)))
    
    # Continue with rest of table style
    table_style_commands.extend([
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), table_font_size),

        # Row 1: Sub-headers - gray background
        ("BACKGROUND", (0, 1), (-1, 1), colors.lightgrey),
        ("TEXTCOLOR", (0, 1), (-1, 1), colors.black),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, 1), table_font_size),
        ("ALIGN", (0, 1), (-1, 1), "CENTER"),

        # Data rows styling
        ("ALIGN", (1, 2), (-1, -1), "CENTER"),
        ("ALIGN", (0, 2), (0, -1), "LEFT"),
        ("FONTSIZE", (0, 2), (-1, -1), table_font_size),

        # Comfortable padding for all cells
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),

        # Grid and borders
        ("GRID", (0, 0), (-1, -1), 0.25, colors.black),
        ("BOX", (0, 0), (-1, -1), 1, colors.black),

        # THICKER LINE between row 1 and row 2 (between headers and data)
        ("LINEBELOW", (0, 1), (-1, 1), 2, colors.black),

        # THICKER LINE between column 0 and column 1 (DATE/TIME and first data column)
        ("LINEAFTER", (0, 0), (0, -1), 2, colors.black),
    ])
    
    table_style = TableStyle(table_style_commands)
    table.setStyle(table_style)
    table.hAlign = 'LEFT'  # Left-justify the table

    elements.append(table)

    # Footer section - Table with column headers (Previous, Present, Units) and row labels
    # Use smaller spacing to keep it compact
    elements.append(Spacer(1, 12))  # Reduced spacing
    
    # Get footer fields from config or use defaults
    footer_fields = report_config.get('footer_fields', [
        "DAILY READING",
        "KWH IN",
        "TOTAL GENERATION",
        "TOTAL KW",
        "KWH OUT"
    ])
    
    # Get footer column headers from config or use defaults
    footer_columns = report_config.get('footer_columns', [""])
    
    # Build footer table data
    # Row 0: Empty cell + column headers
    footer_data = [[""] + footer_columns]
    
    # Subsequent rows: footer field name + empty cells for each column
    for field in footer_fields:
        footer_data.append([field] + [""] * len(footer_columns))

    # Calculate footer table width to match main table width
    # Use the same total width as the main table (calculated above)
    
    # Calculate footer column widths proportionally
    # First column (row labels) gets ~40% of width, rest split equally
    num_footer_cols = len(footer_columns) + 1  # +1 for label column
    label_width = main_table_width * 0.4
    data_col_width = (main_table_width - label_width) / len(footer_columns)
    footer_col_widths = [label_width] + [data_col_width] * len(footer_columns)
    
    footer_table = Table(footer_data, colWidths=footer_col_widths)
    footer_table_style = TableStyle([
        # Row 0 (column headers) - bold, centered, gray background
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),  # Smaller font
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        
        # First column (row labels) - bold, left-aligned, gray background
        ("ALIGN", (0, 1), (0, -1), "LEFT"),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (0, -1), 7),  # Smaller font
        ("BACKGROUND", (0, 1), (0, -1), colors.lightgrey),

        # Data columns (Previous, Present, Units) - centered
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("FONTSIZE", (1, 1), (-1, -1), 7),  # Smaller font

        # All cells - reduced padding for compactness
        ("BOX", (0, 0), (-1, -1), 1, colors.black),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),  # Reduced padding
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        
        # Thicker line below header row
        ("LINEBELOW", (0, 0), (-1, 0), 2, colors.black),
    ])
    footer_table.setStyle(footer_table_style)
    footer_table.hAlign = 'LEFT'  # Left-justify the footer table

    elements.append(footer_table)

    # Build the document - page numbers will be added via callbacks
    doc.build(elements)

    return pdf_path


# def main():
#     """Main function to generate the report."""
#     conn = "23.239.12.151:32349"

#     # the following are user configurable
#     dbms = "cos"
#     increment_unit = "hour"
#     increment_value = 1
#     time_column = "timestamp"
#     start_time = "2025-12-03 00:00:00"
#     end_time = "2025-12-04 00:00:00"
#     monitor_id = "KPL"

#     if not check_data(conn=conn, dbms=dbms):
#         raise ValueError("Failed to locate one or more associated table in cos")

#     end_time = _update_timestamp(end_time=end_time)
#     pp_data = select_power_plant(conn=conn, dbms=dbms, increment_value=increment_value,
#                                  increment_unit=increment_unit, time_column=time_column, start_time=start_time,
#                                  end_time=end_time, monitor_id=monitor_id)
#     tap_data = select_tap_value(conn=conn, dbms=dbms, increment_value=increment_value,
#                                 increment_unit=increment_unit, time_column=time_column, start_time=start_time,
#                                 end_time=end_time)
#     # Create dataframes
#     pp_df = pd.DataFrame(pp_data)
#     tap_df = pd.DataFrame(tap_data)

#     # Extract hour from timestamps for joining
#     pp_df['hour'] = pd.to_datetime(pp_df['min_ts']).dt.floor('h')
#     tap_df['hour'] = pd.to_datetime(tap_df['min_ts']).dt.floor('h')

#     # Merge data on hour
#     merged_df = pd.merge(pp_df, tap_df[['hour', 'tap']], on='hour', how='left')

#     CONFIG = {
#         'start_time': start_time,
#         'end_time': end_time,
#         'monitor_id': monitor_id,
#         'increment_unit': increment_unit,
#         'increment_value': increment_value,
#         'logo_path': "https://tse1.mm.bing.net/th/id/OIP.7bJT74xSx81aYJgz-rl-TwAAAA?cb=ucfimg2&ucfimg=1&rs=1&pid=ImgDetMain&o=7&rm=3",
#         'output_dir': 'outputs',
#         'output_filename': 'power_monitoring_report'
#     }

#     if not os.path.isdir(CONFIG['output_dir']):
#         os.makedirs(CONFIG['output_dir'])

#     CONFIG['logo_path'] = image_download(CONFIG['logo_path'])

#     print("Generating Power Monitoring Report...")
#     print(f"Date Range: {CONFIG['start_time']} to {CONFIG['end_time']}")
#     print(f"Monitor ID: {CONFIG['monitor_id']}")
#     print("-" * 50)

#     # Convert to PDF
#     generate_report(merged_df, CONFIG)

#     print("-" * 50)
#     print("Report generation complete!")


# if __name__ == '__main__':
#     main()
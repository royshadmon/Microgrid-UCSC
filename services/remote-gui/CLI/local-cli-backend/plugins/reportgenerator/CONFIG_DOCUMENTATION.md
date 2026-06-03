# Report Generator Configuration File Documentation

## Table of Contents
1. [Overview](#overview)
2. [Config File Structure](#config-file-structure)
3. [Configuration Sections](#configuration-sections)
   - [Basic Settings](#basic-settings)
   - [Queries](#queries)
   - [Data Merging](#data-merging)
   - [Table Columns](#table-columns)
   - [Footer Fields](#footer-fields)
4. [Creating a Config File](#creating-a-config-file)
5. [Advanced Examples](#advanced-examples)
6. [Troubleshooting](#troubleshooting)

---

## Overview

The Report Generator uses JSON or YAML configuration files to define how reports are generated. These config files allow you to:

- Define custom SQL queries for data retrieval
- Map query results to table columns
- Apply transformations and formatting to data
- Configure how multiple queries are merged
- Customize table structure, column widths, and grouping
- Set report titles, subtitles, and logos
- Define footer fields

**Config files are stored in:** `CLI/local-cli-backend/plugins/reportgenerator/templates/`

**Supported formats:** JSON (`.json`) or YAML (`.yaml`/`.yml`)

---

## Config File Structure

A complete config file has the following structure:

```json
{
  "db_name": "database_name",
  "display_name": "Report Display Name (optional)",
  "title": "Report Title",
  "subtitle": "Report Subtitle (optional)",
  "id": 1,
  "monitor_id": "MONITOR_ID (optional)",
  "logo_url": "https://example.com/logo.png",
  "queries": {
    "query_name_1": "SQL query with placeholders",
    "query_name_2": "Another SQL query"
  },
  "data_merging": {
    "primary_query": "query_name_1",
    "join_key": "hour",
    "join_method": "left",
    "timestamp_field": "min_ts",
    "timestamp_floor": "h"
  },
  "table_columns": {
    "column_definitions": [...],
    "column_groups": {...},
    "column_widths": {...}
  },
  "footer_fields": [...]
}
```

---

## Configuration Sections

### Basic Settings

#### `db_name` (Required)
- **Type:** String
- **Description:** The database name (DBMS) to query from
- **Example:** `"cos"`, `"production_db"`, `"analytics"`

#### `display_name` (Optional)
- **Type:** String
- **Description:** Name displayed in the UI dropdown for selecting reports. If not provided, the system will automatically construct it from `title` and `subtitle` (or just `title` if no subtitle exists)
- **Example:** `"Engine 4 Report"`, `"Main Power Plant - Evergy"`
- **Note:** This field allows you to have a shorter, more user-friendly name in the dropdown while keeping the full title/subtitle for the PDF report

#### `title` (Optional)
- **Type:** String
- **Description:** Main title displayed at the top of the first page
- **Example:** `"CITY OF SABETHA MUNICIPAL POWER PLANT"`

#### `subtitle` (Optional)
- **Type:** String
- **Description:** Subtitle displayed below the main title
- **Example:** `"EVERGY INTERCONNECTION"`
- **Note:** If `id` is set to `0` and a `monitor_id` is provided, the subtitle may be automatically formatted to show engine information (e.g., "Engine #2 (1500 kW)")

#### `monitor_id` (Optional)
- **Type:** String
- **Description:** Pre-configured monitor ID for this report. If specified, the UI will skip the monitor ID selection step and automatically use this value
- **Example:** `"BG8"`, `"ENG1"`, `"KPL2"`
- **Note:** When this field is present, users won't need to select a monitor ID manually - it will be used automatically from the config

#### `id` (Optional)
- **Type:** Integer
- **Description:** Config identifier for special formatting rules
- **Example:** `1` (for engine-specific formatting)
- **Note:** Currently, `id: 1` enables special subtitle formatting that extracts engine numbers from monitor_id

#### `logo_url` (Optional)
- **Type:** String (URL or file path)
- **Description:** URL or local file path to the logo image
- **Supported formats:** PNG, JPG, GIF
- **Example:** 
  - URL: `"https://example.com/logo.png"`
  - Local file: `"/path/to/logo.png"` or `"~/logos/company.png"`

---

### Queries

#### `queries` (Required)
- **Type:** Object (dictionary)
- **Description:** Defines all SQL queries used to fetch data for the report
- **Keys:** Query names (can be any string, e.g., "power_plant", "tap_value", "sensor_data")
- **Values:** SQL query strings with placeholders

#### Query Placeholders

Queries support the following placeholders that are automatically replaced:

- `{increment_unit}` - Time increment unit (e.g., "hour", "minute", "day")
- `{increment_value}` - Time increment value (e.g., 1, 2, 5)
- `{time_column}` - Name of the timestamp column (e.g., "timestamp")
- `{start_time}` - Start timestamp (e.g., "2025-01-01 00:00:00")
- `{end_time}` - End timestamp (e.g., "2025-01-02 00:00:00")
- `{monitor_id}` - Monitor ID (only used if placeholder exists in query)

#### Example Queries

```json
"queries": {
  "power_plant": "SELECT increments({increment_unit}, {increment_value}, {time_column}), monitor_id, MIN(timestamp)::ljust(19) AS min_ts, MAX(timestamp)::ljust(19) AS max_ts, AVG(realpower) AS kw, AVG(a_n_voltage) AS a_kv, AVG(b_n_voltage) AS b_kv, AVG(c_n_voltage) AS c_kv, AVG(powerfactor) AS pf, AVG(a_current) AS amp_1, AVG(b_current) AS amp_2, AVG(c_current) AS amp_3, AVG(frequency) AS hz FROM pp_pm WHERE {time_column} >= '{start_time}' AND {time_column} < '{end_time}' AND monitor_id='{monitor_id}' GROUP BY monitor_id ORDER BY min_ts",
  
  "tap_value": "SELECT increments({increment_unit}, {increment_value}, {time_column}), monitor_id, MIN(timestamp)::ljust(19) AS min_ts, MAX(timestamp)::ljust(19) AS max_ts, AVG(value) AS tap FROM pv WHERE {time_column} >= '{start_time}' AND {time_column} < '{end_time}' GROUP BY monitor_id ORDER BY min_ts",
  
  "sensor_data": "SELECT increments({increment_unit}, {increment_value}, {time_column}), MIN(timestamp) AS min_ts, AVG(temperature) AS temp, AVG(humidity) AS hum FROM sensors WHERE {time_column} >= '{start_time}' AND {time_column} < '{end_time}' GROUP BY monitor_id ORDER BY min_ts"
}
```

**Important Notes:**
- Query names are arbitrary - use descriptive names
- Each query should return a `timestamp` field (or field specified in `data_merging.timestamp_field`)
- Queries are executed independently and then merged
- If a query contains `{monitor_id}`, it will automatically receive the monitor_id parameter

---

### Data Merging

#### `data_merging` (Required)
- **Type:** Object
- **Description:** Configures how multiple query results are merged into a single dataset

#### Fields:

##### `primary_query` (Required)
- **Type:** String
- **Description:** Name of the query to use as the base/primary dataset
- **Example:** `"power_plant"`

##### `join_key` (Required)
- **Type:** String
- **Description:** Field name used to join query results together
- **Example:** `"hour"`, `"timestamp"`, `"date"`

##### `join_method` (Optional, Default: "left")
- **Type:** String
- **Description:** Pandas merge method
- **Options:** `"left"`, `"right"`, `"inner"`, `"outer"`
- **Example:** `"left"` (keeps all rows from primary query)

##### `timestamp_field` (Required)
- **Type:** String
- **Description:** Field name in query results that contains the timestamp
- **Example:** `"min_ts"`, `"timestamp"`, `"created_at"`

##### `timestamp_floor` (Required)
- **Type:** String
- **Description:** Time unit to floor/round timestamps to for joining
- **Options:** `"h"` (hour), `"min"` (minute), `"D"` (day)
- **Example:** `"h"` (rounds to nearest hour)

#### Example:

```json
"data_merging": {
  "primary_query": "power_plant",
  "join_key": "hour",
  "join_method": "left",
  "timestamp_field": "min_ts",
  "timestamp_floor": "h"
}
```

**How it works:**
1. The `primary_query` is executed first and becomes the base dataset
2. All other queries are executed
3. Timestamps from each query are floored to the specified unit (e.g., hour)
4. The floored timestamp becomes the `join_key` (e.g., "hour")
5. All other queries are merged into the primary query using the join_key
6. Only columns needed by `column_definitions` are included in the merge

---

### Table Columns

#### `table_columns` (Required)
- **Type:** Object
- **Description:** Defines the table structure, column mappings, and formatting

#### `column_definitions` (Required)
- **Type:** Array of Objects
- **Description:** Defines each column in the report table

Each column definition object has the following fields:

##### `name` (Required)
- **Type:** String
- **Description:** Display name shown in the table header
- **Example:** `"DATE/TIME"`, `"kW"`, `"Temperature"`

##### `source` (Required)
- **Type:** String or Array of Strings
- **Description:** Field name(s) from query results to use for this column
  - **String:** Single field name (e.g., `"kw"`)
  - **Array:** Multiple field names for calculations (e.g., `["a_kv", "b_kv", "c_kv"]`)
- **Example:** 
  - Single: `"kw"`
  - Multiple: `["a_kv", "b_kv", "c_kv"]`

##### `source_query` (Required)
- **Type:** String
- **Description:** Name of the query (from `queries` section) that provides this data
- **Example:** `"power_plant"`, `"tap_value"`, `"sensor_data"`

##### `transform` (Optional, Default: "none")
- **Type:** String
- **Description:** Transformation to apply to the data
- **Options:**
  - `"none"` - No transformation
  - `"round"` - Round to nearest integer
  - `"divide"` - Divide by `transform_value`
  - `"multiply"` - Multiply by `transform_value`
  - `"average"` - Average multiple source fields (requires array `source`)
  - `"sum"` - Sum multiple source fields (requires array `source`)
  - `"datetime"` - Format as date/time string
- **Example:** `"round"`, `"divide"`, `"average"`

##### `transform_value` (Optional)
- **Type:** Number
- **Description:** Value to use with `divide` or `multiply` transforms
- **Example:** `100` (divide by 100), `0.001` (multiply by 0.001)

##### `format` (Optional, Default: "string")
- **Type:** String
- **Description:** Output format for the value
- **Options:**
  - `"int"` - Integer (rounded)
  - `"float"` - Floating point number
  - `"string"` - String
  - `"datetime"` - Date/time string (use with `transform: "datetime"`)
- **Example:** `"int"`, `"float"`

##### `decimal_places` (Optional, Default: 2)
- **Type:** Integer
- **Description:** Number of decimal places for `float` format
- **Example:** `2`, `3`, `0`

##### `allow_null` (Optional, Default: false)
- **Type:** Boolean
- **Description:** Whether to allow null/empty values (shows as empty string)
- **Example:** `true`, `false`

#### Column Definition Examples:

```json
{
  "name": "DATE/TIME",
  "source": "min_ts",
  "source_query": "power_plant",
  "transform": "datetime",
  "format": "datetime"
}
```

```json
{
  "name": "kW",
  "source": "kw",
  "source_query": "power_plant",
  "transform": "round",
  "format": "int"
}
```

```json
{
  "name": "KV",
  "source": ["a_kv", "b_kv", "c_kv"],
  "source_query": "power_plant",
  "transform": "average",
  "format": "int"
}
```

```json
{
  "name": "PF",
  "source": "pf",
  "source_query": "power_plant",
  "transform": "divide",
  "transform_value": 100,
  "format": "float",
  "decimal_places": 2
}
```

```json
{
  "name": "TAP",
  "source": "tap",
  "source_query": "tap_value",
  "transform": "round",
  "format": "int",
  "allow_null": true
}
```

#### `column_groups` (Optional)
- **Type:** Object
- **Description:** Defines column groups for table headers (e.g., "AMPS", "VOLTAGE")
- **Keys:** Group name (displayed in table)
- **Values:** Array of column indices (0-based) that belong to this group
- **Example:**
```json
"column_groups": {
  "AMPS": [4, 5, 6],
  "VOLTAGE": [7, 8, 9]
}
```

**Note:** Column indices are 0-based and correspond to the order in `column_definitions`.

#### `column_widths` (Optional)
- **Type:** Object
- **Description:** Defines column widths for different page orientations
- **Keys:** `"portrait"` and/or `"landscape"`
- **Values:** Array of numbers (widths in points)
- **Example:**
```json
"column_widths": {
  "portrait": [80, 35, 35, 30, 30, 30, 30, 35, 35, 35, 30, 30],
  "landscape": [120, 50, 50, 40, 50, 50, 50, 50, 50, 50, 40, 40]
}
```

**Note:** 
- Array length should match the number of columns in `column_definitions`
- Widths are automatically scaled if they exceed available page width
- Portrait widths are typically smaller than landscape

---

### Footer Fields

#### `footer_fields` (Optional)
- **Type:** Array of Strings
- **Description:** Row labels for the footer table (displayed in the first column)
- **Example:**
```json
"footer_fields": [
  "DAILY READING",
  "KWH IN",
  "TOTAL GENERATION",
  "TOTAL KW",
  "KWH OUT"
]
```

#### `footer_columns` (Optional)
- **Type:** Array of Strings
- **Description:** Column headers for the footer table (displayed in the header row)
- **Default:** `["Previous", "Present", "Units"]` if not specified
- **Example:**
```json
"footer_columns": [
  "Previous",
  "Present",
  "Units"
]
```
- **Note:** The footer table will have one row for each `footer_fields` entry, with empty cells for each `footer_columns` entry. Users can fill in these values manually on the printed report.

---

## Creating a Config File

### Step-by-Step Guide

1. **Create a new JSON or YAML file** in the templates directory:
   ```
   CLI/local-cli-backend/plugins/reportgenerator/templates/my_report_config.json
   ```

2. **Start with basic structure:**
   ```json
   {
     "db_name": "your_database",
     "title": "Your Report Title",
     "subtitle": "Optional Subtitle",
     "id": 1,
     "logo_url": "https://example.com/logo.png",
     "queries": {},
     "data_merging": {
       "primary_query": "query_name",
       "join_key": "hour",
       "join_method": "left",
       "timestamp_field": "min_ts",
       "timestamp_floor": "h"
     },
     "table_columns": {
       "column_definitions": [],
       "column_groups": {},
       "column_widths": {
         "portrait": [],
         "landscape": []
       }
     },
     "footer_fields": []
   }
   ```

3. **Define your queries:**
   - Identify what data you need
   - Write SQL queries with placeholders
   - Give each query a descriptive name

4. **Define column definitions:**
   - For each column you want in the table:
     - Determine which query provides the data
     - Identify the field name(s) from query results
     - Decide on transformations and formatting
     - Create a column definition object

5. **Configure data merging:**
   - Choose which query is primary
   - Determine how to join queries (timestamp field, join key)
   - Set join method

6. **Set column groups and widths:**
   - Group related columns if needed
   - Set appropriate widths for portrait/landscape

7. **Add footer fields** (optional)

### Example: Simple Single-Query Report

```json
{
  "db_name": "analytics",
  "title": "Daily Sensor Report",
  "subtitle": "Temperature and Humidity Monitoring",
  "logo_url": "https://example.com/logo.png",
  "queries": {
    "sensor_data": "SELECT increments({increment_unit}, {increment_value}, {time_column}), MIN(timestamp) AS min_ts, AVG(temperature) AS temp, AVG(humidity) AS hum FROM sensors WHERE {time_column} >= '{start_time}' AND {time_column} < '{end_time}' GROUP BY monitor_id ORDER BY min_ts"
  },
  "data_merging": {
    "primary_query": "sensor_data",
    "join_key": "hour",
    "join_method": "left",
    "timestamp_field": "min_ts",
    "timestamp_floor": "h"
  },
  "table_columns": {
    "column_definitions": [
      {
        "name": "Time",
        "source": "min_ts",
        "source_query": "sensor_data",
        "transform": "datetime",
        "format": "datetime"
      },
      {
        "name": "Temperature",
        "source": "temp",
        "source_query": "sensor_data",
        "transform": "round",
        "format": "int"
      },
      {
        "name": "Humidity",
        "source": "hum",
        "source_query": "sensor_data",
        "transform": "round",
        "format": "int"
      }
    ],
    "column_groups": {},
    "column_widths": {
      "portrait": [100, 80, 80],
      "landscape": [150, 100, 100]
    }
  },
  "footer_fields": [
    "AVERAGE TEMP",
    "AVERAGE HUMIDITY"
  ]
}
```

### Example: Engine Report with Special Subtitle Formatting

```json
{
  "db_name": "cos",
  "title": "Power Plant Report",
  "subtitle": "Engine Monitoring",
  "id": 1,
  "logo_url": "https://example.com/logo.png",
  "queries": {
    "engine_data": "SELECT increments({increment_unit}, {increment_value}, {time_column}), monitor_id, MIN(timestamp) AS min_ts, AVG(power) AS kw FROM engines WHERE {time_column} >= '{start_time}' AND {time_column} < '{end_time}' AND monitor_id='{monitor_id}' GROUP BY monitor_id ORDER BY min_ts"
  },
  "data_merging": {
    "primary_query": "engine_data",
    "join_key": "hour",
    "join_method": "left",
    "timestamp_field": "min_ts",
    "timestamp_floor": "h"
  },
  "table_columns": {
    "column_definitions": [
      {
        "name": "Time",
        "source": "min_ts",
        "source_query": "engine_data",
        "transform": "datetime",
        "format": "datetime"
      },
      {
        "name": "Power (kW)",
        "source": "kw",
        "source_query": "engine_data",
        "transform": "round",
        "format": "int"
      }
    ],
    "column_widths": {
      "portrait": [100, 100],
      "landscape": [150, 120]
    }
  }
}
```

**Note:** When `id: 1` is set and a `monitor_id` like "ENG2" or "KPL3" is provided, the subtitle will automatically format as "Engine #2 (1500 kW)" or "Engine #3 (850 kW)" based on the engine number extracted from the monitor_id.

---

## Advanced Examples

### Example 1: Multiple Queries with Complex Merging

```json
{
  "db_name": "production",
  "title": "Production Monitoring Report",
  "subtitle": "Multi-Source Data Analysis",
  "queries": {
    "production": "SELECT increments({increment_unit}, {increment_value}, {time_column}), MIN(timestamp) AS min_ts, SUM(units) AS total_units, AVG(efficiency) AS eff FROM production WHERE {time_column} >= '{start_time}' AND {time_column} < '{end_time}' AND monitor_id='{monitor_id}' GROUP BY monitor_id",
    "quality": "SELECT increments({increment_unit}, {increment_value}, {time_column}), MIN(timestamp) AS min_ts, AVG(defect_rate) AS defects FROM quality WHERE {time_column} >= '{start_time}' AND {time_column} < '{end_time}' GROUP BY monitor_id",
    "energy": "SELECT increments({increment_unit}, {increment_value}, {time_column}), MIN(timestamp) AS min_ts, AVG(power_consumption) AS power FROM energy WHERE {time_column} >= '{start_time}' AND {time_column} < '{end_time}' GROUP BY monitor_id"
  },
  "data_merging": {
    "primary_query": "production",
    "join_key": "hour",
    "join_method": "left",
    "timestamp_field": "min_ts",
    "timestamp_floor": "h"
  },
  "table_columns": {
    "column_definitions": [
      {
        "name": "Time",
        "source": "min_ts",
        "source_query": "production",
        "transform": "datetime",
        "format": "datetime"
      },
      {
        "name": "Units",
        "source": "total_units",
        "source_query": "production",
        "transform": "round",
        "format": "int"
      },
      {
        "name": "Efficiency",
        "source": "eff",
        "source_query": "production",
        "transform": "multiply",
        "transform_value": 100,
        "format": "float",
        "decimal_places": 2
      },
      {
        "name": "Defect Rate",
        "source": "defects",
        "source_query": "quality",
        "transform": "multiply",
        "transform_value": 100,
        "format": "float",
        "decimal_places": 3
      },
      {
        "name": "Power (kW)",
        "source": "power",
        "source_query": "energy",
        "transform": "divide",
        "transform_value": 1000,
        "format": "float",
        "decimal_places": 2
      }
    ],
    "column_groups": {
      "PRODUCTION": [1, 2],
      "QUALITY": [3],
      "ENERGY": [4]
    },
    "column_widths": {
      "portrait": [100, 60, 70, 80, 80],
      "landscape": [150, 80, 90, 100, 100]
    }
  },
  "footer_fields": [
    "TOTAL UNITS",
    "AVERAGE EFFICIENCY"
  ]
}
```

### Example 2: Using Array Sources for Calculations

```json
{
  "name": "Average Voltage",
  "source": ["phase_a", "phase_b", "phase_c"],
  "source_query": "power_data",
  "transform": "average",
  "format": "float",
  "decimal_places": 2
}
```

This calculates: `(phase_a + phase_b + phase_c) / 3`

### Example 3: Complex Transformations

```json
{
  "name": "Efficiency %",
  "source": "efficiency_ratio",
  "source_query": "metrics",
  "transform": "multiply",
  "transform_value": 100,
  "format": "float",
  "decimal_places": 1
}
```

This multiplies the value by 100 to convert to percentage.

---

## Troubleshooting

### Common Issues

#### 1. Query Not Found Error
**Error:** `"Query 'my_query' not found in config but required by column definitions"`

**Solution:** 
- Ensure the query name in `queries` matches the `source_query` in column definitions
- Check for typos in query names
- Verify the query exists in the `queries` section

#### 2. Field Not Found in Query Results
**Error:** Column shows empty or incorrect values

**Solution:**
- Verify the `source` field name matches the column name in your SQL query (use `AS` aliases)
- Check that the query actually returns the expected fields
- Ensure `source_query` points to the correct query

#### 3. Merge Fails
**Error:** Data not merging correctly between queries

**Solution:**
- Verify `timestamp_field` exists in all queries
- Check that `timestamp_floor` produces matching values across queries
- Ensure `primary_query` is correct
- Verify `join_key` is created correctly from timestamps

#### 4. Column Width Issues
**Error:** Table gets cut off or columns are too narrow

**Solution:**
- Adjust `column_widths` values
- Ensure array length matches number of columns
- Use smaller widths for portrait, larger for landscape
- System will auto-scale if total exceeds page width

#### 5. Transform Not Working
**Error:** Values not transforming as expected

**Solution:**
- Verify `transform` value is correct (case-sensitive)
- For `divide`/`multiply`, ensure `transform_value` is set
- For `average`/`sum`, ensure `source` is an array
- Check data types - some transforms require numeric values

#### 6. Logo Not Showing
**Error:** Logo doesn't appear in report

**Solution:**
- Verify `logo_url` is accessible (test URL in browser)
- Check file path if using local file
- Ensure image format is supported (PNG, JPG, GIF)
- Check server logs for download errors

### Debugging Tips

1. **Check Query Results:**
   - Test queries directly in your database
   - Verify field names match what's in config
   - Ensure placeholders are replaced correctly

2. **Verify Column Mappings:**
   - Print merged dataframe to see available columns
   - Check that `source` fields exist in merged data
   - Verify `source_query` references are correct

3. **Test Transformations:**
   - Start with simple transforms (`round`, `none`)
   - Add complex transforms incrementally
   - Check intermediate values

4. **Validate Config Structure:**
   - Use JSON/YAML validator
   - Check for missing required fields
   - Verify data types match expected types

---

## Best Practices

1. **Naming Conventions:**
   - Use descriptive query names (e.g., "power_plant_data" not "query1")
   - Use clear column names that match business terminology
   - Keep field names consistent between queries and column definitions

2. **Query Design:**
   - Use `AS` aliases in SQL to match expected field names
   - Always include a timestamp field
   - Use aggregations (AVG, SUM, MIN, MAX) appropriately
   - Test queries independently before adding to config

3. **Column Definitions:**
   - Order columns logically (time first, then data)
   - Group related columns together
   - Use appropriate formats (int for counts, float for measurements)
   - Set `allow_null: true` for optional data

4. **Performance:**
   - Limit query results with proper WHERE clauses
   - Use appropriate time increments
   - Index timestamp columns in database
   - Consider query execution time for large datasets

5. **Maintainability:**
   - Document complex transformations in comments (if using YAML)
   - Keep config files organized and readable
   - Version control your config files
   - Test changes incrementally

---

## Quick Reference

### Required Fields
- `db_name` - Database name
- `queries` - At least one query definition
- `data_merging` - Merge configuration
- `table_columns.column_definitions` - At least one column definition

### Optional Fields
- `title` - Report title
- `subtitle` - Report subtitle
- `id` - Config identifier (for special formatting)
- `logo_url` - Logo URL or path
- `table_columns.column_groups` - Column grouping
- `table_columns.column_widths` - Custom column widths
- `footer_fields` - Footer field labels

### Transform Types
- `none` - No transformation
- `round` - Round to integer
- `divide` - Divide by `transform_value`
- `multiply` - Multiply by `transform_value`
- `average` - Average of multiple sources (requires array)
- `sum` - Sum of multiple sources (requires array)
- `datetime` - Format as date/time

### Format Types
- `int` - Integer
- `float` - Floating point
- `string` - String
- `datetime` - Date/time string

### Join Methods
- `left` - Keep all rows from primary query
- `right` - Keep all rows from secondary queries
- `inner` - Keep only matching rows
- `outer` - Keep all rows from all queries

### Timestamp Floor Options
- `"h"` - Hour
- `"min"` - Minute
- `"D"` - Day

### Special Config Features

#### Engine-Specific Formatting (`id: 1`)
When `id: 1` is set in the config and a `monitor_id` is provided:
- The system attempts to extract an engine number from the monitor_id (e.g., "ENG2" → 2, "KPL3" → 3)
- The subtitle is automatically formatted as "Engine #N (X kW)" where N is the engine number and X is the kW rating
- Supported engine numbers and their kW values are defined in the system
- If parsing fails, falls back to default subtitle display

---

## Support

For issues or questions:
1. Check the troubleshooting section
2. Review example config files in the templates directory
3. Verify your config file syntax with a JSON/YAML validator
4. Check server logs for detailed error messages


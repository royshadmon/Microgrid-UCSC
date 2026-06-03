# Unified Namespace (UNS) Plugin

The Unified Namespace plugin provides a filesystem-like interface for browsing blockchain metadata stored as JSON. It allows you to navigate through hierarchical data structures (namespaces, devices, sensors, etc.) in an intuitive folder-based interface.

## Features

- **Filesystem-like Navigation**: Browse blockchain metadata as if it were a file system with folders and files
- **Hierarchical Structure**: Navigate through parent-child relationships using blockchain queries
- **Breadcrumb Navigation**: Easily navigate back through layers using the breadcrumb trail
- **Item Details**: View full JSON metadata for any item
- **Hover Tooltips**: Quick preview of item details on hover (after 1 second)
- **Side Panel**: Detailed view panel for extended inspection of item data

## How to Use

### Basic Navigation

1. **Select a Node**: Make sure you have a node selected in the application
2. **View Root Items**: The plugin automatically loads root items when a node is selected
3. **Expand Folders**: 
   - **Left-click** on any item to expand it and view its children
   - Items with children show a folder icon (📁) and can be expanded
   - Items without children show a file icon (📄) and cannot be expanded
4. **Navigate Back**: 
   - Use the breadcrumb trail at the top to navigate back to any previous layer
   - Click "🏠 Root" to return to the root level

### Viewing Item Details

1. **Hover Tooltip**:
   - Hover over any item for more than 1 second to see a quick preview tooltip
   - The tooltip shows the item name, type, and full JSON data

2. **Side Panel** (Detailed View):
   - **Right-click** on any item to open the side panel with detailed information
   - The side panel shows:
     - Item name
     - Item type
     - Item ID
     - Full JSON data in a formatted, scrollable view
   - **Right-click again** on the same item to close the side panel
   - Click the "×" button in the panel header to close it

### Understanding the Interface

- **Folder Icons**:
  - 📁 = Item that might have children (not yet checked)
  - 📂 = Item that is expanded (has children)
  - 📄 = Item confirmed to have no children (leaf node)

- **Breadcrumb Trail**: Shows your current path through the hierarchy
  - Click any item in the breadcrumb to navigate back to that layer
  - The current layer is shown in bold

- **Side Panel**: 
  - Opens on the right side of the screen
  - Pushes the folder column to the left (doesn't overlay)
  - Only the folder column scrolls independently
  - Header and breadcrumb remain fixed

## Data Structure

The plugin expects blockchain metadata in the following format:

```json
[
  {
    "key": {
      "id": "item-id",
      "name": "Item Name",
      "parent": "parent-id",
      "namespace": "path/to/item",
      "date": "2026-01-18T01:04:04.975229Z",
      "ledger": "global"
    }
  }
]
```

Where `key` can be any type (e.g., `namespace`, `device`, `sensor`, `config`, `master`, `cluster`, etc.).

## Blockchain Commands Used

The plugin uses the following blockchain commands:

- **Get Root Items**: `blockchain get *`
- **Get Item by ID**: `blockchain get * where [id] = "item-id"`
- **Get Children**: `blockchain get * where [id] = "item-id" bring.children`

## Keyboard Shortcuts

- **Scroll**: Use mouse wheel or scrollbar to scroll within the folder column
- **Refresh**: Click the "🔄 Refresh" button to reload root items

## Tips

1. **Long Lists**: If you have many items, use the scrollbar in the folder column to navigate
2. **Finding Items**: The plugin automatically extracts names from the `name` or `id` fields in the JSON
3. **Empty Children**: If an item returns an empty array when checking for children, it's marked as a leaf node
4. **Navigation**: The breadcrumb shows your full path - use it to quickly jump back to any level

## Troubleshooting

- **"Unknown" Items**: If items show as "Unknown", check that the JSON structure has either a `name` or `id` field in the nested data object
- **No Children Loading**: Check the browser console and backend logs to see the exact command being executed
- **Side Panel Not Opening**: Make sure you're right-clicking on an item, not left-clicking
- **Scrolling Issues**: Only the folder column should scroll - if the whole page scrolls, check that the container has proper height constraints

## Technical Details

- **Frontend**: React component with state management for layers, paths, and expanded items
- **Backend**: FastAPI endpoints that execute blockchain commands and parse responses
- **Caching**: The plugin caches which items have children to avoid unnecessary API calls
- **Responsive**: The side panel smoothly animates in/out and adjusts the layout accordingly


# Bookmark Refresh Functionality

This guide explains how bookmarks now refresh automatically when you add a new bookmark.

## How It Works

### 1. Automatic Refresh
When you bookmark a node in the NodePicker component:
1. The bookmark is saved to the backend
2. A global event `bookmark-refresh` is dispatched
3. The UserProfile component listens for this event
4. The bookmarks list is automatically refreshed

### 2. Manual Refresh
You can also manually refresh bookmarks by:
1. Clicking the "Refresh" button in the UserProfile page
2. The bookmarks list will reload from the server

## Implementation Details

### NodePicker Component
```javascript
const handleBookmark = async () => {
    // ... bookmark logic ...
    await bookmarkNode({ node: selectedNode });
    
    // Dispatch global event to refresh bookmarks
    window.dispatchEvent(new Event('bookmark-refresh'));
};
```

### UserProfile Component
```javascript
useEffect(() => {
    refreshBookmarks();
    
    // Listen for bookmark refresh events
    const handleBookmarkRefresh = () => {
        refreshBookmarks();
    };
    
    window.addEventListener('bookmark-refresh', handleBookmarkRefresh);
    
    return () => {
        window.removeEventListener('bookmark-refresh', handleBookmarkRefresh);
    };
}, []);
```

## User Experience

### Before
- User bookmarks a node
- User has to manually navigate to UserProfile page
- User has to refresh the page to see the new bookmark

### After
- User bookmarks a node
- If UserProfile page is open, bookmarks refresh automatically
- User can also manually refresh with the "Refresh" button
- No page reload needed

## Testing

1. **Open the app**: http://localhost:3000
2. **Login** with your account
3. **Navigate to UserProfile** page
4. **Go back to Client** page
5. **Bookmark a node** using the NodePicker
6. **Navigate back to UserProfile** - the bookmark should appear immediately
7. **Try the manual refresh** button

## Benefits

- ✅ **Immediate feedback**: Bookmarks appear right away
- ✅ **No page reloads**: Smooth user experience
- ✅ **Manual control**: Users can refresh manually if needed
- ✅ **Global events**: Works across different components
- ✅ **Clean implementation**: Uses standard browser events

## Technical Notes

- Uses browser's native `Event` system
- No external dependencies required
- Works with React's component lifecycle
- Automatically cleans up event listeners
- Compatible with the file-based authentication system 
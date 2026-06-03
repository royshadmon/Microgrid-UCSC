# Frontend Integration with File-Based Authentication

This document explains how the frontend has been updated to work with the new file-based authentication system.

## New Service: `file_auth.js`

The new `file_auth.js` service replaces the old JWT-based authentication system with a file-based approach.

### Key Changes

1. **No JWT Tokens**: Uses user IDs stored in localStorage instead of JWT tokens
2. **Automatic Authentication**: All API calls automatically include the user ID
3. **Simplified API**: No need to pass authentication tokens manually
4. **Better Error Handling**: Proper error messages from the server

## Updated Components

### 1. Login Component (`Login.js`)
- ✅ Updated to use `file_auth.js`
- ✅ Stores user ID instead of JWT tokens
- ✅ Handles login errors properly

### 2. Signup Component (`Signup.js`)
- ✅ Updated to use `file_auth.js`
- ✅ Stores user ID and user info in localStorage
- ✅ Handles signup errors properly

### 3. UserProfile Component (`UserProfile.js`)
- ✅ Updated to use `file_auth.js` for bookmarks
- ✅ Removed JWT parameter from API calls
- ✅ Uses automatic authentication

### 4. Presets Component (`Presets.js`)
- ✅ Updated to use `file_auth.js` for preset groups and presets
- ✅ Removed JWT parameter from API calls
- ✅ Updated response format handling

### 5. Client Component (`Client.js`)
- ✅ Updated to use `file_auth.js` for preset groups and presets
- ✅ Removed JWT parameter from API calls
- ✅ Maintains existing functionality

### 6. NodePicker Component (`NodePicker.js`)
- ✅ Updated to use `file_auth.js` for bookmarks
- ✅ Removed JWT parameter from API calls
- ✅ Uses automatic authentication

## API Endpoints Used

### Authentication
- `POST /auth/signup/` - User registration
- `POST /auth/login/` - User login
- `POST /auth/get-user/` - Get user information
- `GET /auth/logout/` - User logout

### Bookmarks
- `POST /auth/bookmark-node/` - Add bookmark
- `POST /auth/get-bookmarked-nodes/` - Get bookmarks
- `POST /auth/delete-bookmarked-node/` - Delete bookmark
- `POST /auth/update-bookmark-description/` - Update bookmark description

### Preset Groups
- `POST /auth/add-preset-group/` - Add preset group
- `POST /auth/get-preset-groups/` - Get preset groups
- `POST /auth/delete-preset-group/` - Delete preset group

### Presets
- `POST /auth/add-preset/` - Add preset to group
- `POST /auth/get-presets/` - Get presets by group

## localStorage Structure

The new system stores user data in localStorage:

```javascript
localStorage.setItem('userId', 'user-uuid');
localStorage.setItem('userEmail', 'user@example.com');
localStorage.setItem('userFirstName', 'John');
localStorage.setItem('userLastName', 'Doe');
```

## Error Handling

The new service provides better error handling:

```javascript
try {
    const result = await signup({ email, password, firstName, lastName });
    // Success
} catch (error) {
    // Error message from server
    console.error(error.message);
}
```

## Testing

A test file `file_auth.test.js` is included for testing the service:

```javascript
// Run in browser console
await testFileAuth();
```

## Migration from Old System

### Before (JWT-based):
```javascript
// Old way
const jwt = localStorage.getItem('accessToken');
const result = await getBookmarks({ jwt });
```

### After (File-based):
```javascript
// New way
const result = await getBookmarks(); // Automatic authentication
```

## Benefits

1. **Simpler Code**: No need to manually pass JWT tokens
2. **Better Security**: No JWT tokens stored in localStorage
3. **Easier Debugging**: User ID is human-readable
4. **Consistent API**: All endpoints follow the same pattern
5. **Better Error Handling**: Proper error messages from server

## Usage Examples

### User Registration
```javascript
import { signup } from '../services/file_auth';

const result = await signup({
    email: 'user@example.com',
    password: 'password123',
    firstName: 'John',
    lastName: 'Doe'
});
```

### User Login
```javascript
import { login } from '../services/file_auth';

const result = await login({
    email: 'user@example.com',
    password: 'password123'
});
```

### Add Bookmark
```javascript
import { bookmarkNode } from '../services/file_auth';

const result = await bookmarkNode({ node: 'server:8080' });
```

### Get Bookmarks
```javascript
import { getBookmarks } from '../services/file_auth';

const result = await getBookmarks();
```

### Add Preset Group
```javascript
import { addPresetGroup } from '../services/file_auth';

const result = await addPresetGroup({ name: 'My Group' });
```

### Add Preset
```javascript
import { addPreset } from '../services/file_auth';

const result = await addPreset({
    preset: {
        group_id: 'group-uuid',
        command: 'blockchain get *',
        type: 'GET',
        button: 'Get All'
    }
});
```

## Backward Compatibility

The old `auth.js` and `presetsApi.js` services are still available but deprecated. New components should use `file_auth.js`.

## Future Improvements

1. **TypeScript Support**: Add TypeScript definitions
2. **React Hooks**: Create custom hooks for authentication
3. **Context Provider**: Add React context for user state
4. **Offline Support**: Add offline capabilities
5. **Real-time Updates**: Add WebSocket support for real-time updates 
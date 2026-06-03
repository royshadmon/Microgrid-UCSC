# File-Based Authentication System

This document explains how to use the file-based authentication system that replaces the JWT/session-based Supabase authentication.

## Overview

The file-based authentication system stores user data, bookmarks, and presets in JSON files instead of using a database. This provides a simple, stateless authentication system without the need for JWT tokens or sessions.

## Files

- `file_auth.py` - Core authentication functions
- `file_auth_router.py` - FastAPI router with all authentication endpoints
- `main.py` - Updated to use the file_auth_router
- `users.json` - User data storage
- `bookmarks.json` - Bookmark data storage
- `presets.json` - Preset data storage
- `preset_groups.json` - Preset group data storage

## API Endpoints

All authentication endpoints are now prefixed with `/auth/`:

### Authentication
- `POST /auth/signup/` - Register a new user
- `POST /auth/login/` - Authenticate a user
- `POST /auth/get-user/` - Get user information
- `GET /auth/logout/` - Logout (no server-side action needed)

### Bookmarks
- `POST /auth/bookmark-node/` - Add a bookmark
- `POST /auth/get-bookmarked-nodes/` - Get all bookmarks
- `POST /auth/delete-bookmarked-node/` - Delete a bookmark
- `POST /auth/update-bookmark-description/` - Update bookmark description

### Preset Groups
- `POST /auth/add-preset-group/` - Add a preset group
- `POST /auth/get-preset-groups/` - Get all preset groups
- `POST /auth/delete-preset-group/` - Delete a preset group

### Presets
- `POST /auth/add-preset/` - Add a preset to a group
- `POST /auth/get-presets/` - Get presets for a specific group

## Request/Response Format

### Signup
```json
POST /auth/signup/
{
  "email": "user@example.com",
  "password": "password123",
  "firstname": "John",
  "lastname": "Doe"
}

Response:
{
  "data": {
    "user": {
      "id": "uuid",
      "email": "user@example.com",
      "firstname": "John",
      "lastname": "Doe",
      "created_at": "2024-01-01T00:00:00"
    }
  }
}
```

### Login
```json
POST /auth/login/
{
  "email": "user@example.com",
  "password": "password123"
}

Response:
{
  "data": {
    "user": {
      "id": "uuid",
      "email": "user@example.com",
      "firstname": "John",
      "lastname": "Doe",
      "created_at": "2024-01-01T00:00:00"
    }
  }
}
```

### Get User
```json
POST /auth/get-user/
{
  "jwt": "user_id_here"
}

Response:
{
  "data": {
    "id": "uuid",
    "email": "user@example.com",
    "firstname": "John",
    "lastname": "Doe",
    "created_at": "2024-01-01T00:00:00"
  }
}
```

### Bookmark Node
```json
POST /auth/bookmark-node/
{
  "jwt": "user_id_here",
  "conn": "node:8080"
}

Response:
{
  "data": {
    "bookmark": {
      "id": "uuid",
      "user_id": "user_id",
      "node": "node:8080",
      "description": "",
      "created_at": "2024-01-01T00:00:00"
    }
  }
}
```

### Add Preset Group
```json
POST /auth/add-preset-group/
{
  "jwt": "user_id_here",
  "group": {
    "group_name": "My Group"
  }
}

Response:
{
  "data": {
    "group": {
      "id": "uuid",
      "user_id": "user_id",
      "group_name": "My Group",
      "created_at": "2024-01-01T00:00:00"
    }
  }
}
```

## Frontend Integration

The frontend should store the user ID in localStorage instead of JWT tokens:

```javascript
// After successful login/signup
localStorage.setItem('userId', userData.id);
localStorage.setItem('userEmail', userData.email);
localStorage.setItem('userFirstName', userData.firstname);
localStorage.setItem('userLastName', userData.lastname);

// For API calls, use the user ID as the "jwt" field
const requestBody = {
  jwt: localStorage.getItem('userId'),
  // ... other data
};
```

## Testing

Run the test script to verify the router works:

```bash
cd CLI/Local-CLI/local-cli-backend
python test_router.py
```

## Benefits

1. **Simple**: No database setup required
2. **Stateless**: No sessions or tokens to manage
3. **Portable**: Data stored in JSON files
4. **Fast**: Direct file access
5. **Easy to debug**: Human-readable JSON files

## Security Considerations

- Passwords are hashed using SHA-256
- User IDs are UUIDs for uniqueness
- File permissions should be set appropriately
- Consider backing up JSON files regularly

## Migration from Supabase

To migrate from the old Supabase system:

1. Export user data from Supabase
2. Convert to the new JSON format
3. Update frontend to use user IDs instead of JWT tokens
4. Update API calls to use the new `/auth/` endpoints 
// File-based service (no authentication required)
// Simplified version that works without user authentication

const API_URL = window._env_?.REACT_APP_API_URL || "http://localhost:8000";

// Default user ID for all operations
const DEFAULT_USER_ID = "default-user-12345";

// Set default user ID in localStorage on first load
if (!localStorage.getItem('userId')) {
    localStorage.setItem('userId', DEFAULT_USER_ID);
}

// Authentication functions (simplified)
export async function signup({ email, password, firstName, lastName }) {
    // Always return success with default user
    const defaultUser = {
        id: DEFAULT_USER_ID,
        email: email || "default@example.com",
        firstname: firstName || "Default",
        lastname: lastName || "User",
        created_at: new Date().toISOString()
    };
    
    localStorage.setItem('userId', DEFAULT_USER_ID);
    localStorage.setItem('userEmail', defaultUser.email);
    localStorage.setItem('userFirstName', defaultUser.firstname);
    localStorage.setItem('userLastName', defaultUser.lastname);
    
    return { data: { user: defaultUser } };
}

export async function login({ email, password }) {
    // Always return success with default user
    const defaultUser = {
        id: DEFAULT_USER_ID,
        email: email || "default@example.com",
        firstname: "Default",
        lastname: "User",
        created_at: new Date().toISOString()
    };
    
    localStorage.setItem('userId', DEFAULT_USER_ID);
    localStorage.setItem('userEmail', defaultUser.email);
    localStorage.setItem('userFirstName', defaultUser.firstname);
    localStorage.setItem('userLastName', defaultUser.lastname);
    
    return { data: { user: defaultUser } };
}

export async function logout() {
    // Clear localStorage but keep default user ID
    localStorage.removeItem('userEmail');
    localStorage.removeItem('userFirstName');
    localStorage.removeItem('userLastName');
    
    // Keep the default user ID
    localStorage.setItem('userId', DEFAULT_USER_ID);
    
    return { data: { message: "Logged out successfully" } };
}

export async function getUser() {
    // Always return default user
    const defaultUser = {
        id: DEFAULT_USER_ID,
        email: localStorage.getItem('userEmail') || "default@example.com",
        firstname: localStorage.getItem('userFirstName') || "Default",
        lastname: localStorage.getItem('userLastName') || "User",
        created_at: new Date().toISOString()
    };
    
    return { data: defaultUser };
}

export function isLoggedIn() {
    // Always return true - no authentication needed
    return true;
}

// Bookmark functions (simplified - no authentication required)
export async function bookmarkNode({ node }) {
    if (!node) {
        throw new Error('Missing node parameter');
    }
    console.log("Bookmarking node: ", node);

    try {
        const requestBody = { conn: { conn: node } };

        const response = await fetch(`${API_URL}/auth/bookmark-node/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
            throw new Error(`Server responded with status ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error bookmarking node:', error);
        throw error;
    }
}

export async function getBookmarks() {
    try {
        const response = await fetch(`${API_URL}/auth/get-bookmarked-nodes/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
        });

        if (!response.ok) {
            throw new Error(`Server responded with status ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error getting bookmarks:', error);
        throw error;
    }
}

export async function deleteBookmarkedNode({ node }) {
    if (!node) {
        throw new Error('Missing node parameter');
    }

    try {
        const requestBody = { conn: { conn: node } };

        const response = await fetch(`${API_URL}/auth/delete-bookmarked-node/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
            throw new Error(`Server responded with status ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error deleting bookmarked node:', error);
        throw error;
    }
}

export async function updateBookmarkDescription({ node, description }) {
    if (!node || !description) {
        throw new Error('Missing node or description parameter');
    }

    try {
        const requestBody = {
            node: node,
            description: description
        };

        const response = await fetch(`${API_URL}/auth/update-bookmark-description/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
            throw new Error(`Server responded with status ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error updating bookmark description:', error);
        throw error;
    }
}

export async function setDefaultBookmark({ node }) {
    if (!node) {
        throw new Error('Missing node parameter');
    }

    try {
        const requestBody = { conn: { conn: node } };

        const response = await fetch(`${API_URL}/auth/set-default-bookmark/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
            throw new Error(`Server responded with status ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error setting default bookmark:', error);
        throw error;
    }
}

// Preset group functions (simplified - no authentication required)
export async function addPresetGroup({ name }) {
    if (!name) {
        throw new Error('Missing group name');
    }

    try {
        const requestBody = { group_name: name };

        const response = await fetch(`${API_URL}/auth/add-preset-group/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
            throw new Error(`Server responded with status ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error adding preset group:', error);
        throw error;
    }
}

export async function getPresetGroups() {
    try {
        const response = await fetch(`${API_URL}/auth/get-preset-groups/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
        });

        if (!response.ok) {
            throw new Error(`Server responded with status ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error getting preset groups:', error);
        throw error;
    }
}

export async function deletePresetGroup({ groupId, groupName }) {
    if (!groupId || !groupName) {
        throw new Error('Missing group ID or group name');
    }

    try {
        const requestBody = {
            group_id: groupId,
            group_name: groupName
        };

        console.log("Delete group request body:", requestBody);

        const response = await fetch(`${API_URL}/auth/delete-preset-group/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
            const errorText = await response.text();
            console.error("Delete group response error:", response.status, errorText);
            throw new Error(`Server responded with status ${response.status}: ${errorText}`);
        }

        const data = await response.json();
        console.log("Delete group response:", data);
        return data;
    } catch (error) {
        console.error('Error deleting preset group:', error);
        throw error;
    }
}

// Preset functions (simplified - no authentication required)
export async function addPreset({ preset }) {
    if (!preset || !preset.command || !preset.type || !preset.button || !preset.group_id) {
        throw new Error('Missing required preset fields');
    }

    try {
        const requestBody = preset;

        console.log("Request body: ", requestBody);

        const response = await fetch(`${API_URL}/auth/add-preset/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
            throw new Error(`Server responded with status ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error adding preset:', error);
        throw error;
    }
}

export async function getPresetsByGroup({ groupId }) {
    if (!groupId) {
        throw new Error('Missing group ID');
    }

    try {
        const requestBody = { group_id: groupId };

        console.log("Request body: ", requestBody);

        const response = await fetch(`${API_URL}/auth/get-presets/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
            throw new Error(`Server responded with status ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error getting presets by group:', error);
        throw error;
    }
}

export async function deletePreset({ presetId }) {
    if (!presetId) {
        throw new Error('Missing preset ID');
    }

    try {
        const requestBody = { preset_id: presetId };

        console.log("Delete preset request body: ", requestBody);

        const response = await fetch(`${API_URL}/auth/delete-preset/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
            throw new Error(`Server responded with status ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error deleting preset:', error);
        throw error;
    }
}

// Utility functions
export function getCurrentUser() {
    return {
        id: localStorage.getItem('userId') || DEFAULT_USER_ID,
        email: localStorage.getItem('userEmail') || "default@example.com",
        firstName: localStorage.getItem('userFirstName') || "Default",
        lastName: localStorage.getItem('userLastName') || "User"
    };
}

export function clearUserData() {
    localStorage.removeItem('userEmail');
    localStorage.removeItem('userFirstName');
    localStorage.removeItem('userLastName');
    // Keep the default user ID
    localStorage.setItem('userId', DEFAULT_USER_ID);
} 
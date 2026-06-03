// Default user ID for all operations (no authentication needed)
const DEFAULT_USER_ID = "default-user-12345";

// Set default user ID in localStorage on first load
if (!localStorage.getItem('userId')) {
    localStorage.setItem('userId', DEFAULT_USER_ID);
}

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
    return { data: { user: defaultUser } };
}

export async function logout() {
    // Clear localStorage but keep default user ID
    localStorage.removeItem('accessToken');
    localStorage.removeItem('refreshToken');
    localStorage.removeItem('expiresAt');
    
    // Keep the default user ID
    localStorage.setItem('userId', DEFAULT_USER_ID);
    
    return { data: { message: "Logged out successfully" } };
}

export async function getUser() {
    // Always return default user
    const defaultUser = {
        id: DEFAULT_USER_ID,
        email: "default@example.com",
        firstname: "Default",
        lastname: "User",
        created_at: new Date().toISOString()
    };
    
    return { data: defaultUser };
}

export function isLoggedIn() {
    // Always return true - no authentication needed
    return true;
}
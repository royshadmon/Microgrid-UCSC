// api.js

// const API_BASE_URL = process.env.NODE_ENV === 'production' 
//   ? "/api/security"  // In production (Docker), use relative path for nginx proxy
//   : "http://localhost:8000/security"; // In development, use direct backend URL

const API_BASE_URL = (window._env_?.REACT_APP_API_URL || "http://localhost:8000") + "/security";

export async function login(nodeAddress, pubkey) {
  if (!nodeAddress || !pubkey) {
    return { error: "Missing node address or pubkey" };
  }

  try {
    const response = await fetch(`${API_BASE_URL}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        node: nodeAddress,
        pubkey: pubkey
      }),
    });

    if (!response.ok) {
      const error = await response.json();
      return { error: error.detail || "Login failed" };
    }

    const data = await response.json();
    return { success: true, data };
  } catch (err) {
    console.error("Login error:", err);
    return { error: "Could not connect to server" };
  }
}


export async function submitPolicy(nodeAddress, policyType, formData, memberPubkey = null, signingMemberName = null) {
  if (!nodeAddress || !policyType || !formData) {
    return { error: "Missing required inputs" };
  }

  try {
    const requestBody = {
      node: nodeAddress,
      policy_file: policyType,
      policy: formData
    };

    // Add member public key if provided
    if (memberPubkey) {
      requestBody.member_pubkey = memberPubkey;
    }

    // Add signing member name if provided
    if (signingMemberName) {
      requestBody.signing_member_name = signingMemberName;
    }

    const response = await fetch(`${API_BASE_URL}/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    });

    if (!response.ok) {
      const error = await response.json();
      return { error: error.detail || "Submission failed" };
    }

    const data = await response.json();
    return { success: true, data };
  } catch (err) {
    console.error("Submit policy error:", err);
    return { error: "Could not connect to server" };
  }
}


export async function getPolicyTemplate(policyType) {
  try {
    const response = await fetch(`${API_BASE_URL}/policy-template/${policyType}`);
    return await response.json();
  } catch (err) {
    console.error("Failed to fetch policy template", err);
    return null;
  }
}

export async function fetchPolicyTypes() {
  try {
    const response = await fetch(`${API_BASE_URL}/policy-types`);
    const data = await response.json();

    if (response.ok && data.types) {
      return data.types; // expected to be an array of { type, name }
    } else {
      console.error("Invalid policy types response:", data);
      return [];
    }
  } catch (error) {
    console.error("Error fetching policy types:", error);
    return [];
  }
}

export async function fetchNodeOptions(nodeAddress) {
  try {
    const res = await fetch(`${API_BASE_URL}/node-options/${nodeAddress}`);
    const data = await res.json();
    return data.options || [];
  } catch (error) {
    console.error("Error fetching node options:", error);
    return [];
  }
}

export async function fetchTableOptions(nodeAddress) {
  try {
    const res = await fetch(`${API_BASE_URL}/table-options/${nodeAddress}`);
    const data = await res.json();
    return data.options || [];
  } catch (error) {
    console.error("Error fetching table options:", error);
    return [];
  }
}


export async function fetchCustomTypes() {
  try {
    const response = await fetch(`${API_BASE_URL}/custom-types`);
    if (!response.ok) {
      const error = await response.json();
      return { error: error.detail || "Failed to fetch custom types" };
    }
    const data = await response.json();
    return data.custom_types || [];
  } catch (err) {
    console.error("fetchCustomTypes error:", err);
    return { error: "Could not connect to server" };
  }
}



export async function fetchTypeOptions(nodeAddress, type) {
  try {
    const response = await fetch(`${API_BASE_URL}/type-options`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        node: nodeAddress,
        type: type
      }),
    });

    if (!response.ok) {
      const error = await response.json();
      return { error: error.detail || "Failed to fetch type options" };
    }

    const data = await response.json();
    return data.options || [];
  } catch (err) {
    console.error("fetchTypeOptions error:", err);
    return { error: "Could not connect to server" };
  }
}


export async function pingBackend() {
  try {
    const response = await fetch(`${API_BASE_URL}/ping`);
    if (!response.ok) throw new Error("Ping failed");
    return await response.json();
  } catch (err) {
    console.error("API ping error:", err);
    return null;
  }
}

export async function fetchAvailablePermissions(nodeAddress) {
  try {
    const res = await fetch(`${API_BASE_URL}/permissions/${nodeAddress}`);
    console.log("res:", res)
    if (!res.ok) return [];
    const data = await res.json();
    console.log("[DEBUG] Frontend received permissions data:", data);
    
    // Backend now returns a flat array of permission names
    if (Array.isArray(data)) {
      console.log("[DEBUG] Permissions array:", data);
      return data;
    }
    
    // Fallback: if backend still returns an object, try to extract permissions array
    if (data && Array.isArray(data.permissions)) {
      console.log("[DEBUG] Extracted permissions from object:", data.permissions);
      return data.permissions;
    }
    
    console.log("[DEBUG] No valid permissions found, returning empty array");
    return [];
  } catch (err) {
    console.error("fetchAvailablePermissions error:", err);
    return [];
  }
}

export async function fetchUserPermissions(node, pubkey) {
  // console.log("Fetching user permissions for:", node, pubkey);
  try {
    const response = await fetch(`${API_BASE_URL}/user-permissions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ node, pubkey }),
    });
    // console.log("User permissions response:", response);
    if (!response.ok) {
      const error = await response.json();
      return { error: error.detail || "Failed to fetch user permissions" };
    }
    const data = await response.json();
    return { success: true, data };
  } catch (err) {
    console.error("fetchUserPermissions error:", err);
    return { error: "Could not connect to server" };
  }
}

// Assignment Management API functions
export async function assignmentSummary(node) {
  try {
    const response = await fetch(`${API_BASE_URL}/assignment-summary`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        node: node
      }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Failed to fetch assignment summary");
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error("Error fetching assignment summary:", error);
    throw error;
  }
}

export async function regenerateAssignments(node, securityGroup = null) {
  try {
    const requestBody = {
      node: node
    };
    
    if (securityGroup) {
      requestBody.security_group = securityGroup;
    }

    const response = await fetch(`${API_BASE_URL}/regenerate-assignments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Failed to regenerate assignments");
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error("Error regenerating assignments:", error);
    throw error;
  }
}

export async function fetchAvailableSigningMembers(node, pubkey) {
  try {
    const response = await fetch(`${API_BASE_URL}/available-signing-members`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ node, pubkey }),
    });

    if (!response.ok) {
      const error = await response.json();
      return { error: error.detail || "Failed to fetch available signing members" };
    }

    const data = await response.json();
    console.log("[DEBUG] Frontend received signing members:", data);
    return { success: true, data: data.members || [] };
  } catch (err) {
    console.error("fetchAvailableSigningMembers error:", err);
    return { error: "Could not connect to server" };
  }
}

export async function debugMembers(node) {
  try {
    const response = await fetch(`${API_BASE_URL}/debug-members/${node}`);
    if (!response.ok) {
      const error = await response.json();
      return { error: error.detail || "Failed to debug members" };
    }
    const data = await response.json();
    console.log("[DEBUG] Frontend debug members response:", data);
    return { success: true, data };
  } catch (err) {
    console.error("debugMembers error:", err);
    return { error: "Could not connect to server" };
  }
}
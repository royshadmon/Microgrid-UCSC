
export async function addPresetGroup({ jwt, name }) {
  if (!jwt || !name) {
    alert('Missing required fields Preset Group');
    return;
  }

  console.log("addPresetGroup called with jwt:", jwt, "and group name:", name);

  try {

    const requestBody = { token: { jwt: jwt }, group: { group_name: name } };

    const response = await fetch(`http://127.0.0.1:8000/add-preset-group/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        // Possibly include auth headers or other tokens here
      },
      body: JSON.stringify(requestBody),
    });

    console.log("Response: ", response);

    if (!response.ok) {
      throw new Error(`Server responded with status ${response.status},  ${response}`);
    }

    // Parse JSON response
    const respData = await response.json();
    return respData;
  } catch (error) {
    // Optionally handle errors
    console.error('Error getting nodes:', error);
    throw error; // re-throw so the component knows there was an error
  }
}



export async function getPresetGroups({ jwt }) {
  if (!jwt) {
    alert('Missing required fields Get Preset Groups');
    return;
  }


  console.log("getPresetGroup called with jwt:", jwt);


  try {

    const requestBody = { jwt: jwt };

    const response = await fetch(`http://127.0.0.1:8000/get-preset-groups/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        // Possibly include auth headers or other tokens here
      },
      body: JSON.stringify(requestBody),
    });

    console.log("Response: ", response);

    if (!response.ok) {
      throw new Error(`Server responded with status ${response.status},  ${response}`);
    }

    // Parse JSON response
    const respData = await response.json();
    console.log("Preset groups data:", respData);
    return respData;
  } catch (error) {
    // Optionally handle errors
    console.error('Error getting nodes:', error);
    throw error; // re-throw so the component knows there was an error
  }
}


export async function addPreset({ jwt, preset }) {
  if (!jwt || !preset || !preset.command || !preset.type || !preset.button || !preset.group_id) {
    alert('Missing required fields');
    return;
  }

  console.log("addPresetGroup called with jwt:", jwt, "and preset:", preset);

  try {

    const requestBody = { token: { jwt: jwt }, preset: preset };

    const response = await fetch(`http://127.0.0.1:8000/add-preset/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        // Possibly include auth headers or other tokens here
      },
      body: JSON.stringify(requestBody),
    });

    console.log("Response: ", response);

    if (!response.ok) {
      throw new Error(`Server responded with status ${response.status},  ${response}`);
    }

    // Parse JSON response
    const respData = await response.json();
    return respData;
  } catch (error) {
    // Optionally handle errors
    console.error('Error getting nodes:', error);
    throw error; // re-throw so the component knows there was an error
  }
}


export async function getPresetsByGroup({ jwt, groupId }) {
  if (!jwt) {
    alert('Missing required fields get presets by group');
    return;
  }


  console.log("getPresetsByGroup called with jwt:", jwt, "and groupId:", groupId);


  try {

    const requestBody = { token: { jwt: jwt }, group_id: { group_id: groupId } };

    const response = await fetch(`http://127.0.0.1:8000/get-presets/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        // Possibly include auth headers or other tokens here
      },
      body: JSON.stringify(requestBody),
    });

    console.log("Response: ", response);

    if (!response.ok) {
      throw new Error(`Server responded with status ${response.status},  ${response}`);
    }

    // Parse JSON response
    const respData = await response.json();
    console.log("Preset by groups data:", respData);
    return respData;
  } catch (error) {
    // Optionally handle errors
    console.error('Error getting nodes:', error);
    throw error; // re-throw so the component knows there was an error
  }
}


export async function deletePresetGroup({ jwt, groupId, gname }) {
  if (!jwt) {
    alert('Missing required fields');
    return;
  }

  console.log("deletePresetGroup called with jwt:", jwt, "and groupId:", groupId, "and group name:", gname);


  try {

    const requestBody = { token: { jwt: jwt }, group_id: { group_id: groupId }, group: { group_name: gname } };


    const response = await fetch(`http://127.0.0.1:8000/delete-preset-group/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        // Possibly include auth headers or other tokens here
      },
      body: JSON.stringify(requestBody),
    });

    console.log("Response: ", response);

    if (!response.ok) {
      throw new Error(`Server responded with status ${response.status},  ${response}`);
    }

    // Parse JSON response
    const respData = await response.json();
    console.log("Preset by groups data:", respData);
    return respData;
  } catch (error) {
    // Optionally handle errors
    console.error('Error getting nodes:', error);
    throw error; // re-throw so the component knows there was an error
  }
}



export async function getBasePresetPolicy() {
  try {

    const response = await fetch(`http://127.0.0.1:8000/get-preset-policy/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        // Possibly include auth headers or other tokens here
      },
      body: '',
    });

    console.log("Response: ", response);

    if (!response.ok) {
      throw new Error(`Server responded with status ${response.status},  ${response}`);
    }

    // Parse JSON response
    const respData = await response.json();
    console.log("Preset by groups data:", respData);
    return respData;
  } catch (error) {
    // Optionally handle errors
    console.error('Error getting nodes:', error);
    throw error; // re-throw so the component knows there was an error
  }
}
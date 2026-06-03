import React, { useState } from "react";
import { addData } from "../services/api"; // Adjust the import path as needed
import "../styles/AddData.css";

const AddData = ({ node }) => {
  const [dbmsName, setDbmsName] = useState("");
  const [tableName, setTableName] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [submittedId, setSubmittedId] = useState(null);

  // Handle JSON file selection and parsing
  const handleFileChange = (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    setError(null);
    const reader = new FileReader();
    reader.onload = (evt) => {
      try {
        const parsed = JSON.parse(evt.target.result);
        setData(parsed);
      } catch (err) {
        setError("Invalid JSON file. Please upload a valid JSON.");
        setData(null);
      }
    };
    reader.readAsText(file);
  };

  // Submit the data
  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!dbmsName.trim() || !tableName.trim()) {
      setError("Please enter both DBMS name and table name.");
      return;
    }
    if (!data) {
      setError("No data to submit. Please upload a JSON file.");
      return;
    }
    // if (!node) {
    //   setError("No node information provided.");
    //   return;

    // }

    setError(null);
    setLoading(true);
    setSubmittedId(null);

    console.log("Node:", node);

    try {
      // Example payload structure; adjust as needed
      // const payload = {
      //   connectInfo: node,
      //   dbms: dbmsName,
      //   table: tableName,
      //   data,
      // };
      const result = await addData({ connectInfo: node, db: dbmsName, table: tableName, data });
      console.log("Result:", result);
      // setSubmittedId(result.data.id);
      // console.log("Payload to submit:", payload);
      setSubmittedId("60 seconds"); // remove when using real API
    } catch (err) {
      setError(err.message || "Failed to add data.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container">
      <h2>Add Data via JSON File</h2>

      {/* DBMS name input */}
      <label htmlFor="dbmsName">DBMS Name:</label>
      <br />
      <input
        id="dbmsName"
        type="text"
        placeholder="DBMS Name"
        value={dbmsName}
        onChange={(e) => setDbmsName(e.target.value)}
        className="text-input"
      />
      <br />

      {/* Table name input */}
      <label htmlFor="tableName">Table Name:</label>
      <br />
      <input
      id="tableName"
        type="text"
        placeholder="Table Name"
        value={tableName}
        onChange={(e) => setTableName(e.target.value)}
        className="text-input"
      />

      {/* File upload input */}
      <div className="file-input-group">
        <input
          type="file"
          accept=".json"
          onChange={handleFileChange}
        />
      </div>

      {/* JSON preview */}
      {data && (
        <>
          <h3>JSON Preview:</h3>
          <pre className="json-preview">
            {JSON.stringify({ data }, null, 2)}
          </pre>
        </>
      )}

      {/* Error message */}
      {error && <div className="error-message">{error}</div>}

      {/* Submit button */}
      <button
        onClick={handleSubmit}
        className="submit-btn"
        disabled={loading || !data}
      >
        {loading ? "Submitting..." : "Submit Data"}
      </button>

      {/* Show ID after submission */}
      {submittedId && (
        <div className="id-box">
          <p>Data inserted successfully!</p>
          <p><strong>Time remaining to complete data push:</strong> {submittedId}</p>
        </div>
      )}
    </div>
  );
};

export default AddData;

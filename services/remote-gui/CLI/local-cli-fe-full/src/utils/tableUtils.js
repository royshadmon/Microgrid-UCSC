// Utility functions for table data processing

// Internal columns that should be hidden by default
const INTERNAL_COLUMNS = ['row_id', 'tsd_name', 'tsd_id'];

/**
 * Filters out internal columns from table data
 * @param {Array} data - Array of objects representing table rows
 * @param {boolean} showInternal - Whether to show internal columns
 * @returns {Object} - Object with filtered data and headers
 */
export const filterTableData = (data, showInternal = false) => {
  if (!Array.isArray(data) || data.length === 0) {
    return { data: [], headers: [] };
  }

  // Get all headers from the first row
  const allHeaders = Object.keys(data[0]);
  
  // Filter headers based on showInternal flag
  const filteredHeaders = showInternal 
    ? allHeaders 
    : allHeaders.filter(header => !INTERNAL_COLUMNS.includes(header));

  // Filter data to only include the filtered headers
  const filteredData = data.map(row => {
    const filteredRow = {};
    filteredHeaders.forEach(header => {
      filteredRow[header] = row[header];
    });
    return filteredRow;
  });

  return {
    data: filteredData,
    headers: filteredHeaders,
    hasInternalColumns: allHeaders.some(header => INTERNAL_COLUMNS.includes(header))
  };
};

/**
 * Checks if data contains any internal columns
 * @param {Array} data - Array of objects representing table rows
 * @returns {boolean} - True if data contains internal columns
 */
export const hasInternalColumns = (data) => {
  if (!Array.isArray(data) || data.length === 0) {
    return false;
  }
  
  const headers = Object.keys(data[0]);
  return headers.some(header => INTERNAL_COLUMNS.includes(header));
};

/**
 * Gets the count of internal columns in the data
 * @param {Array} data - Array of objects representing table rows
 * @returns {number} - Number of internal columns found
 */
export const getInternalColumnCount = (data) => {
  if (!Array.isArray(data) || data.length === 0) {
    return 0;
  }
  
  const headers = Object.keys(data[0]);
  return headers.filter(header => INTERNAL_COLUMNS.includes(header)).length;
};

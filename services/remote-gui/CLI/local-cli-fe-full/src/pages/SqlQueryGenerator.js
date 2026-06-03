import React, { useState, useEffect } from 'react';
import { getDatabases, getTables, getColumns, sendCommand } from '../services/api';
import DataTable from '../components/DataTable';
import '../styles/SqlQueryGenerator.css';

// run client () sql opcua_demo format = table "SELECT min(value), max(value), avg(value) FROM t11 WHERE period(hour, 3, now(), timestamp)"
// implement:
// periods
// increments
// better where clause (where columns >=/==/<= value)
// better aggregators
// make exceptions for timestamps


const SqlQueryGenerator = ({ node }) => {
  const [databases, setDatabases] = useState([]);
  const [selectedDatabase, setSelectedDatabase] = useState('');
  const [tables, setTables] = useState([]);
  const [selectedTable, setSelectedTable] = useState('');
  const [columns, setColumns] = useState([]);
  const [selectedColumns, setSelectedColumns] = useState([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [whereClause, setWhereClause] = useState('');
  const [whereConditions, setWhereConditions] = useState([]);
  const [periods, setPeriods] = useState([]);
  const [groupBy, setGroupBy] = useState('');
  const [groupByColumns, setGroupByColumns] = useState([]);
  const [orderBy, setOrderBy] = useState('');
  const [orderByColumns, setOrderByColumns] = useState([]);
  const [limit, setLimit] = useState('');
  const [format, setFormat] = useState('json');
  const [timezone, setTimezone] = useState('utc');
  const [distinct, setDistinct] = useState(false);
  const [aggregations, setAggregations] = useState([]);
  const [joins, setJoins] = useState([]);
  
  // Include tables state for cross-database queries
  const [includeTables, setIncludeTables] = useState([]);
  
  // Extend fields state for additional query fields
  const [extendFields, setExtendFields] = useState([]);
  
  // Target nodes state for dynamic node discovery and filtering
  const [useTargetNodes, setUseTargetNodes] = useState(false);
  const [operators, setOperators] = useState([]);
  const [operatorFilters, setOperatorFilters] = useState([]);
  const [selectedNodes, setSelectedNodes] = useState([]);
  const [loadingOperators, setLoadingOperators] = useState(false);
  
  // Validation state
  const [groupByRequired, setGroupByRequired] = useState(false);
  
  // Column selection mode state
  const [columnMode, setColumnMode] = useState('columns'); // 'columns', 'aggregations', or 'mixed'
  
  // Time-series analysis mode state
  const [timeSeriesMode, setTimeSeriesMode] = useState('none'); // 'none', 'increments', or 'periods'
  
  // Increments function state
  const [useIncrements, setUseIncrements] = useState(false);
  const [incrementsUnit, setIncrementsUnit] = useState('minute');
  const [incrementsInterval, setIncrementsInterval] = useState(1);
  const [incrementsDateColumn, setIncrementsDateColumn] = useState('');

  // Execution state
  const [executing, setExecuting] = useState(false);
  const [executionResult, setExecutionResult] = useState(null);
  const [executionError, setExecutionError] = useState(null);
  const [executionTime, setExecutionTime] = useState(null);
  const [additionalContent, setAdditionalContent] = useState(null);

  // Fetch databases on component mount
  useEffect(() => {
    if (node) {
      fetchDatabases();
    }
  }, [node]);

  // Fetch tables when database changes
  useEffect(() => {
    if (selectedDatabase) {
      fetchTables();
    } else {
      setTables([]);
      setSelectedTable('');
    }
  }, [selectedDatabase]);

  // Fetch columns when table changes
  useEffect(() => {
    if (selectedTable) {
      fetchColumns();
    } else {
      setColumns([]);
      setSelectedColumns([]);
    }
  }, [selectedTable]);

  // Update query when selections change
  useEffect(() => {
    buildQuery();
  }, [selectedColumns, whereConditions, periods, groupBy, groupByColumns, orderBy, orderByColumns, limit, format, timezone, distinct, aggregations, joins, useIncrements, incrementsUnit, incrementsInterval, incrementsDateColumn, columnMode, timeSeriesMode, includeTables, extendFields, useTargetNodes, selectedNodes, operatorFilters]);

  const fetchDatabases = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getDatabases({ connectInfo: node });
      setDatabases(result.data || []);
    } catch (err) {
      setError('Failed to fetch databases: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchTables = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getTables({ connectInfo: node, database: selectedDatabase });
      setTables(result.data || []);
    } catch (err) {
      setError('Failed to fetch tables: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchColumns = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getColumns({ 
        connectInfo: node, 
        database: selectedDatabase, 
        table: selectedTable 
      });
      setColumns(result.data || []);
    } catch (err) {
      setError('Failed to fetch columns: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const buildQuery = () => {
    // Check if we have any content to build a query with
    const hasRegularColumns = (columnMode === 'columns' || columnMode === 'mixed') && selectedColumns.length > 0;
    const hasAggregations = (columnMode === 'aggregations' || columnMode === 'mixed') && aggregations.length > 0 && aggregations.some(agg => {
      if (!agg.function) return false;
      // Handle special functions like count(*)
      if (agg.isSpecialFunction && agg.column === '*') return true;
      // Handle regular column-based aggregations
      if (!agg.column) return false;
      // Check if column is aggregatable
      if (!isAggregatableColumn(agg.column)) return false;
      // For date/time columns, only MIN and MAX are valid
      if (isDateColumn(agg.column) && agg.function !== 'MIN' && agg.function !== 'MAX') return false;
      return true;
    });
    const hasPeriods = periods.length > 0 && periods.some(period => period.timeScale && period.amount && period.startValue && period.column);
    const hasIncrements = useIncrements && incrementsDateColumn;
    
    // If no columns and no aggregations, don't build a query
    if (!hasRegularColumns && !hasAggregations) {
      setQuery('');
      return;
    }

    // Check for conflicts between periods and increments
    if (hasPeriods && hasIncrements) {
      setQuery('');
      return;
    }

    // Check if increments requires aggregations
    if (hasIncrements && !hasAggregations) {
      setQuery('');
      return;
    }

    // Check if GROUP BY is required (when mixing aggregations with non-aggregated columns)
    const hasMixedColumns = (columnMode === 'mixed' || (columnMode === 'aggregations' && selectedColumns.length > 0)) && 
                           selectedColumns.length > 0 && hasAggregations;
    const hasGroupBy = groupByColumns.length > 0 || groupBy.trim() !== '';
    
    if (hasMixedColumns && !hasGroupBy) {
      setGroupByRequired(true);
      setQuery('');
      return;
    } else {
      setGroupByRequired(false);
    }

    // Build AnyLog SQL query: run client () sql [dbms] [query options] [select statement]
    let anylogQuery = 'run client ';
    
    // Add target nodes if specified
    if (useTargetNodes) {
      const nodeSelectionQuery = buildNodeSelectionQuery();
      anylogQuery += `(${nodeSelectionQuery}) `;
    } else {
      anylogQuery += '() ';
    }
    
    anylogQuery += 'sql ';
    
    // Add database name
    anylogQuery += selectedDatabase;
    
    // Add query options (format and timezone)
    anylogQuery += ` format = ${format}`;
    if (timezone !== 'utc') {
      anylogQuery += ` timezone = ${timezone}`;
    }
    
    // Add include tables if specified
    const validIncludeTables = includeTables.filter(table => table.tableName.trim() !== '');
    if (validIncludeTables.length > 0) {
      const tableNames = validIncludeTables.map(table => table.tableName.trim());
      anylogQuery += ` and include=(${tableNames.join(', ')})`;
    }
    
    // Add extend fields if specified
    const validExtendFields = extendFields.filter(field => field.fieldName.trim() !== '');
    if (validExtendFields.length > 0) {
      const fieldNames = validExtendFields.map(field => field.fieldName.trim());
      anylogQuery += ` and extend=(${fieldNames.join(', ')})`;
    }
    
    // Start the SELECT statement
    anylogQuery += ' "';
    
    // Add SELECT keyword
    anylogQuery += 'SELECT ';
    
    // Add DISTINCT if selected
    if (distinct) {
      anylogQuery += 'DISTINCT ';
    }
    
    // Build the SELECT clause with columns and aggregations
    let selectClause = '';
    
    // Add increments function if enabled
    if (hasIncrements) {
      selectClause += `increments(${incrementsUnit}, ${incrementsInterval}, ${incrementsDateColumn}), `;
      // Add min and max of the date column automatically
      selectClause += `min(${incrementsDateColumn}), max(${incrementsDateColumn})`;
    }
    
    // Add selected columns (in columns mode or mixed mode)
    if (columnMode === 'columns' || columnMode === 'mixed') {
      if (selectedColumns.length > 0) {
        if (selectClause.length > 0) {
          selectClause += ', ';
        }
        selectClause += selectedColumns.join(', ');
      }
    }
    
    // Add aggregations (in aggregations mode or mixed mode)
    if (columnMode === 'aggregations' || columnMode === 'mixed') {
      aggregations.forEach((agg, index) => {
        if (agg.function) {
          // Handle special functions like count(*)
          if (agg.isSpecialFunction && agg.column === '*') {
            // Add comma if there are previous columns
            if (selectClause.length > 0) {
              selectClause += ', ';
            }
            
            const alias = agg.alias || `${agg.function.toLowerCase()}_all`;
            selectClause += `${agg.function}(*) as ${alias}`;
            return;
          }
          
          // Handle regular column-based aggregations
          if (agg.column) {
            // Validate that column is aggregatable
            if (!isAggregatableColumn(agg.column)) {
              return; // Skip non-aggregatable columns
            }
            // Validate that date/time columns only use MIN or MAX
            if (isDateColumn(agg.column) && agg.function !== 'MIN' && agg.function !== 'MAX') {
              return; // Skip invalid aggregations
            }
            
            // Add comma if there are previous columns
            if (selectClause.length > 0) {
              selectClause += ', ';
            }
            
            const alias = agg.alias || `${agg.function.toLowerCase()}_${agg.column}`;
            selectClause += `${agg.function}(${agg.column}) as ${alias}`;
          }
        }
      });
    }
    
    anylogQuery += selectClause;
    
    // Add FROM clause
    anylogQuery += ` FROM ${selectedTable}`;
    
    // Add JOIN clauses
    joins.forEach(join => {
      anylogQuery += ` ${join.type} JOIN ${join.table} ON ${join.condition}`;
    });
    
    // Add WHERE clause
    if (whereConditions.length > 0 || periods.length > 0) {
      const validConditions = whereConditions.filter(condition => 
        condition.column && condition.operator && condition.value !== undefined && condition.value !== ''
      );
      
      const validPeriods = periods.filter(period => 
        period.timeScale && period.amount && period.startValue !== undefined && period.startValue !== '' && period.column
      );
      
      const whereParts = [];
      
      // Add regular WHERE conditions
      if (validConditions.length > 0) {
        const conditionStrings = validConditions.map((condition, index) => {
          // Handle different value types
          let value = condition.value;
          if (condition.value === 'NOW()') {
            value = 'NOW()';
          } else if (typeof condition.value === 'string' && !condition.value.startsWith('NOW()')) {
            // Quote string values unless they're functions
            value = `'${condition.value}'`;
          }
          
          const conditionString = `${condition.column} ${condition.operator} ${value}`;
          
          // Add logical operator for all conditions except the first one
          if (index > 0) {
            const logicalOp = condition.logicalOperator || 'AND';
            return `${logicalOp} ${conditionString}`;
          }
          
          return conditionString;
        });
        whereParts.push(...conditionStrings);
      }
      
      // Add period conditions
      if (validPeriods.length > 0) {
        const periodStrings = validPeriods.map(period => {
          let startValue = period.startValue;
          if (period.startValue === 'NOW()') {
            startValue = 'NOW()';
          } else if (typeof period.startValue === 'string' && !period.startValue.startsWith('NOW()')) {
            // Quote string values unless they're functions
            startValue = `'${period.startValue}'`;
          }
          return `period(${period.timeScale}, ${period.amount}, ${startValue}, ${period.column})`;
        });
        whereParts.push(...periodStrings);
      }
      
      if (whereParts.length > 0) {
        anylogQuery += ` WHERE ${whereParts.join(' ')}`;
      }
    }
    
    // Add GROUP BY clause
    if (groupByColumns.length > 0) {
      anylogQuery += ` and GROUP BY ${groupByColumns.join(', ')}`;
    } else if (groupBy.trim()) {
      anylogQuery += ` and GROUP BY ${groupBy}`;
    }
    
    // Add ORDER BY clause
    if (orderByColumns.length > 0) {
      const orderByClause = orderByColumns.map(col => {
        const direction = col.direction || 'ASC';
        return `${col.column} ${direction}`;
      }).join(', ');
      anylogQuery += ` ORDER BY ${orderByClause}`;
    } else if (orderBy.trim()) {
      anylogQuery += ` ORDER BY ${orderBy}`;
    }
    
    // Add LIMIT clause
    if (limit.trim()) {
      anylogQuery += ` LIMIT ${limit}`;
    }
    
    // Close the SELECT statement with quotes
    anylogQuery += '"';
    
    setQuery(anylogQuery);
  };

  const handleColumnToggle = (column) => {
    setSelectedColumns(prev => {
      if (prev.includes(column)) {
        return prev.filter(col => col !== column);
      } else {
        return [...prev, column];
      }
    });
  };

  const handleSelectAllColumns = () => {
    setSelectedColumns(columns.map(col => col.column_name || col.name));
  };

  const handleClearColumns = () => {
    setSelectedColumns([]);
  };

  const handleGroupByColumnToggle = (column) => {
    setGroupByColumns(prev => {
      if (prev.includes(column)) {
        return prev.filter(col => col !== column);
      } else {
        return [...prev, column];
      }
    });
  };

  const handleSelectAllGroupByColumns = () => {
    setGroupByColumns(columns.map(col => col.column_name || col.name));
  };

  const handleClearGroupByColumns = () => {
    setGroupByColumns([]);
  };

  const handleOrderByColumnToggle = (column) => {
    setOrderByColumns(prev => {
      const existingIndex = prev.findIndex(col => col.column === column);
      if (existingIndex >= 0) {
        return prev.filter(col => col.column !== column);
      } else {
        return [...prev, { column, direction: 'ASC' }];
      }
    });
  };

  const handleSelectAllOrderByColumns = () => {
    const newOrderByColumns = columns.map(col => ({
      column: col.column_name || col.name,
      direction: 'ASC'
    }));
    setOrderByColumns(newOrderByColumns);
  };

  const handleClearOrderByColumns = () => {
    setOrderByColumns([]);
  };

  const handleOrderByDirectionChange = (column, direction) => {
    setOrderByColumns(prev => 
      prev.map(col => 
        col.column === column ? { ...col, direction } : col
      )
    );
  };

  const fetchOperators = async () => {
    if (!node) {
      setError('No node connected. Please connect to a node first.');
      return;
    }

    setLoadingOperators(true);
    setError(null);
    
    try {
      const result = await sendCommand({
        connectInfo: node,
        method: 'GET',
        command: 'blockchain get operator'
      });
      
      if (result && result.data) {
        setOperators(result.data);
        // Extract unique filter keys from operators
        const filterKeys = new Set();
        result.data.forEach(op => {
          if (op.operator) {
            Object.keys(op.operator).forEach(key => {
              if (key !== 'ip' && key !== 'port' && key !== 'rest_port' && key !== 'broker_port') {
                filterKeys.add(key);
              }
            });
          }
        });
        console.log('Available filter keys:', Array.from(filterKeys));
      }
    } catch (err) {
      setError('Failed to fetch operators: ' + err.message);
      console.error('Error fetching operators:', err);
    } finally {
      setLoadingOperators(false);
    }
  };

  const addOperatorFilter = () => {
    const newFilter = {
      id: Date.now(),
      key: '',
      operator: '=',
      value: ''
    };
    setOperatorFilters([...operatorFilters, newFilter]);
  };

  const removeOperatorFilter = (id) => {
    setOperatorFilters(operatorFilters.filter(filter => filter.id !== id));
  };

  const updateOperatorFilter = (id, field, value) => {
    setOperatorFilters(operatorFilters.map(filter => 
      filter.id === id ? { ...filter, [field]: value } : filter
    ));
  };

  const buildNodeSelectionQuery = () => {
    if (operatorFilters.length === 0) {
      return 'blockchain get operator bring.ip_port';
    }

    const validFilters = operatorFilters.filter(filter => 
      filter.key && filter.operator && filter.value !== undefined && filter.value !== ''
    );

    if (validFilters.length === 0) {
      return 'blockchain get operator bring.ip_port';
    }

    const filterClause = validFilters.map(filter => {
      let value = filter.value;
      // Quote string values unless they're numbers or booleans
      if (isNaN(value) && value !== 'true' && value !== 'false') {
        value = `"${value}"`;
      }
      return `${filter.key}${filter.operator}${value}`;
    }).join(' and ');

    return `blockchain get operator where ${filterClause} bring.ip_port`;
  };

  const handleColumnModeChange = (mode) => {
    setColumnMode(mode);
    // Clear the other mode's data when switching to exclusive modes
    if (mode === 'columns') {
      setAggregations([]);
    } else if (mode === 'aggregations') {
      setSelectedColumns([]);
    }
    // For 'mixed' mode, keep both columns and aggregations
  };

  const handleTimeSeriesModeChange = (mode) => {
    setTimeSeriesMode(mode);
    // Clear the other mode's data when switching
    if (mode === 'increments') {
      setPeriods([]);
      setUseIncrements(true);
    } else if (mode === 'periods') {
      setUseIncrements(false);
      setIncrementsDateColumn('');
    } else {
      // 'none' mode
      setUseIncrements(false);
      setIncrementsDateColumn('');
      setPeriods([]);
    }
  };

  const copyQuery = () => {
    if (query.trim()) {
      navigator.clipboard.writeText(query).then(() => {
        // Could add a toast notification here
        console.log('Query copied to clipboard');
      }).catch(err => {
        console.error('Failed to copy query:', err);
      });
    }
  };

  const executeQuery = async () => {
    if (!query.trim()) {
      setExecutionError('No query to execute. Please build a query first.');
      return;
    }

    if (!node) {
      setExecutionError('No node connected. Please connect to a node first.');
      return;
    }

    // Basic validation for AnyLog SQL query format
    if (!query.startsWith('run client (')) {
      setExecutionError('Invalid query format. Query should start with "run client () sql"');
      return;
    }

    setExecuting(true);
    setExecutionError(null);
    setExecutionResult(null);
    setExecutionTime(null);
    setAdditionalContent(null);

    try {
      console.log('Executing query:', query);
      const startTime = Date.now();
      
      const result = await sendCommand({
        connectInfo: node,
        method: 'GET',
        command: query
      });

      const endTime = Date.now();
      const executionTimeMs = endTime - startTime;
      
      console.log('Query execution result:', result);
      setExecutionResult(result);
      setExecutionError(null);
      setExecutionTime(executionTimeMs);
      
      // Store additional content if present
      if (result.additional_content) {
        setAdditionalContent(result.additional_content);
      } else {
        setAdditionalContent(null);
      }
    } catch (err) {
      console.error('Query execution error:', err);
      setExecutionError(`Execution failed: ${err.message}`);
      setExecutionResult(null);
      setExecutionTime(null);
      setAdditionalContent(null);
    } finally {
      setExecuting(false);
    }
  };

  const clearQuery = () => {
    setSelectedDatabase('');
    setSelectedTable('');
    setSelectedColumns([]);
    setQuery('');
    setWhereClause('');
    setWhereConditions([]);
    setPeriods([]);
    setGroupBy('');
    setGroupByColumns([]);
    setOrderBy('');
    setOrderByColumns([]);
    setLimit('');
    setFormat('json');
    setTimezone('utc');
    setDistinct(false);
    setAggregations([]);
    setJoins([]);
    setUseIncrements(false);
    setIncrementsUnit('minute');
    setIncrementsInterval(1);
    setIncrementsDateColumn('');
    setExecutionResult(null);
    setExecutionError(null);
  };

  const clearResults = () => {
    setExecutionResult(null);
    setExecutionError(null);
    setExecutionTime(null);
    setAdditionalContent(null);
  };

  const addAggregation = () => {
    // Find the first aggregatable column
    const firstAggregatableColumn = columns.find(col => 
      isAggregatableColumn(col.column_name || col.name)
    );
    
    const newAgg = {
      id: Date.now(),
      column: firstAggregatableColumn ? (firstAggregatableColumn.column_name || firstAggregatableColumn.name) : '',
      function: 'COUNT',
      alias: '',
      isSpecialFunction: false // New field to track special functions like count(*)
    };
    setAggregations([...aggregations, newAgg]);
  };

  const removeAggregation = (id) => {
    console.log('Removing aggregation with id:', id);
    console.log('Current aggregations:', aggregations);
    setAggregations(aggregations.filter(agg => agg.id !== id));
  };

  const updateAggregation = (id, field, value) => {
    setAggregations(aggregations.map(agg => {
      if (agg.id === id) {
        const updatedAgg = { ...agg, [field]: value };
        
        // If updating the function, check if it's a special function
        if (field === 'function') {
          if (value === 'COUNT' && updatedAgg.column === '*') {
            updatedAgg.isSpecialFunction = true;
          } else {
            updatedAgg.isSpecialFunction = false;
          }
        }
        
        // If updating the column, validate it's aggregatable
        if (field === 'column') {
          // Special case for count(*)
          if (value === '*') {
            updatedAgg.isSpecialFunction = true;
            updatedAgg.function = 'COUNT';
          } else {
            updatedAgg.isSpecialFunction = false;
            // If it's a date/time column, ensure function is valid
            if (isDateColumn(value)) {
              if (updatedAgg.function !== 'MIN' && updatedAgg.function !== 'MAX') {
                updatedAgg.function = 'MIN'; // Default to MIN for date/time columns
              }
            }
            // If it's not an aggregatable column, clear the function
            else if (!isAggregatableColumn(value)) {
              updatedAgg.function = '';
            }
          }
        }
        
        return updatedAgg;
      }
      return agg;
    }));
  };

  const getAggregationPreview = (agg) => {
    if (!agg.function) return '';
    
    // Handle special functions like count(*)
    if (agg.isSpecialFunction && agg.column === '*') {
      const alias = agg.alias || `${agg.function.toLowerCase()}_all`;
      return `${agg.function}(*) as ${alias}`;
    }
    
    // Handle regular column-based aggregations
    if (!agg.column) return '';
    const alias = agg.alias || `${agg.function.toLowerCase()}_${agg.column}`;
    return `${agg.function}(${agg.column}) as ${alias}`;
  };

  const addWhereCondition = () => {
    const newCondition = {
      id: Date.now(),
      column: '',
      operator: '=',
      value: '',
      logicalOperator: 'AND' // Default to AND
    };
    setWhereConditions([...whereConditions, newCondition]);
  };

  const removeWhereCondition = (id) => {
    setWhereConditions(whereConditions.filter(condition => condition.id !== id));
  };

  const updateWhereCondition = (id, field, value) => {
    setWhereConditions(whereConditions.map(condition => 
      condition.id === id ? { ...condition, [field]: value } : condition
    ));
  };

  const setNowValue = (id) => {
    updateWhereCondition(id, 'value', 'NOW()');
  };

  const isDateColumn = (columnName) => {
    const column = columns.find(col => (col.column_name || col.name) === columnName);
    if (!column) return false;
    const type = (column.data_type || column.type || '').toLowerCase();
    return type.includes('date') || type.includes('time') || type.includes('timestamp');
  };

  const isNumericColumn = (columnName) => {
    const column = columns.find(col => (col.column_name || col.name) === columnName);
    if (!column) return false;
    const type = (column.data_type || column.type || '').toLowerCase();
    return type.includes('int') || type.includes('float') || type.includes('double') || 
           type.includes('decimal') || type.includes('numeric') || type.includes('real') ||
           type.includes('bigint') || type.includes('smallint') || type.includes('tinyint');
  };

  const isAggregatableColumn = (columnName) => {
    return isDateColumn(columnName) || isNumericColumn(columnName);
  };

  const addPeriod = () => {
    const newPeriod = {
      id: Date.now(),
      timeScale: 'hour',
      amount: 1,
      startValue: 'NOW()',
      column: ''
    };
    setPeriods([...periods, newPeriod]);
  };

  const removePeriod = (id) => {
    setPeriods(periods.filter(period => period.id !== id));
  };

  const updatePeriod = (id, field, value) => {
    setPeriods(periods.map(period => 
      period.id === id ? { ...period, [field]: value } : period
    ));
  };

  const setPeriodNowValue = (id) => {
    updatePeriod(id, 'startValue', 'NOW()');
  };

  const getPeriodPreview = (period) => {
    if (!period.timeScale || !period.amount || !period.startValue || !period.column) return '';
    let startValue = period.startValue;
    if (period.startValue === 'NOW()') {
      startValue = 'NOW()';
    } else if (typeof period.startValue === 'string' && !period.startValue.startsWith('NOW()')) {
      startValue = `'${period.startValue}'`;
    }
    return `period(${period.timeScale}, ${period.amount}, ${startValue}, ${period.column})`;
  };

  const addJoin = () => {
    const newJoin = {
      id: Date.now(),
      type: 'INNER',
      table: '',
      condition: ''
    };
    setJoins([...joins, newJoin]);
  };

  const removeJoin = (id) => {
    console.log('Removing join with id:', id);
    console.log('Current joins:', joins);
    setJoins(joins.filter(join => join.id !== id));
  };

  const updateJoin = (id, field, value) => {
    setJoins(joins.map(join => 
      join.id === id ? { ...join, [field]: value } : join
    ));
  };

  const addIncludeTable = () => {
    const newIncludeTable = {
      id: Date.now(),
      tableName: ''
    };
    setIncludeTables([...includeTables, newIncludeTable]);
  };

  const removeIncludeTable = (id) => {
    setIncludeTables(includeTables.filter(table => table.id !== id));
  };

  const updateIncludeTable = (id, field, value) => {
    setIncludeTables(includeTables.map(table => 
      table.id === id ? { ...table, [field]: value } : table
    ));
  };

  const addExtendField = () => {
    const newExtendField = {
      id: Date.now(),
      fieldName: ''
    };
    setExtendFields([...extendFields, newExtendField]);
  };

  const removeExtendField = (id) => {
    setExtendFields(extendFields.filter(field => field.id !== id));
  };

  const updateExtendField = (id, field, value) => {
    setExtendFields(extendFields.map(fieldItem => 
      fieldItem.id === id ? { ...fieldItem, [field]: value } : fieldItem
    ));
  };

  const populateDefaultExtendFields = () => {
    const defaultFields = [
      { id: Date.now(), fieldName: '+ip' },
      { id: Date.now() + 1, fieldName: '+overlay_ip' },
      { id: Date.now() + 2, fieldName: '+hostname' },
      { id: Date.now() + 3, fieldName: '@table_name' }
    ];
    setExtendFields(defaultFields);
  };

  return (
    <div className="sql-query-generator">
      <h2>AnyLog Query Generator</h2>
      <p><strong>Connected Node:</strong> {node}</p>
      {/* <p className="query-description">
        Build AnyLog SQL queries with the format: <code>run client () sql [dbms] [options] "[SELECT statement]"</code>
      </p> */}

      <div className="query-builder-container">
        {/* Database and Table Selection */}
        <div className="selection-panel">
          <div className="selection-group">
            <label>Database:</label>
            <select 
              value={selectedDatabase} 
              onChange={(e) => setSelectedDatabase(e.target.value)}
              disabled={loading}
            >
              <option value="">Select Database</option>
              {databases.map((db, index) => (
                <option key={index} value={db.database_name || db.name}>
                  {db.database_name || db.name}
                </option>
              ))}
            </select>
          </div>

          <div className="selection-group">
            <label>Table:</label>
            <select 
              value={selectedTable} 
              onChange={(e) => setSelectedTable(e.target.value)}
              disabled={!selectedDatabase || loading}
            >
              <option value="">Select Table</option>
              {tables.map((table, index) => (
                <option key={index} value={table.table_name || table.name}>
                  {table.table_name || table.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Target Nodes Selection */}
        <div className="target-nodes-panel">
          <div className="panel-header">
            <h3>Target Nodes</h3>
            <div className="target-nodes-toggle">
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={useTargetNodes}
                  onChange={(e) => setUseTargetNodes(e.target.checked)}
                />
                <span className="toggle-slider"></span>
              </label>
              <span className="toggle-label">Enable Target Nodes</span>
            </div>
          </div>
          
          {useTargetNodes && (
            <div className="target-nodes-content">
              <div className="target-nodes-actions">
                <button 
                  onClick={fetchOperators} 
                  className="btn-primary"
                  disabled={loadingOperators}
                >
                  {loadingOperators ? 'Fetching...' : 'Fetch Available Operators'}
                </button>
                <button 
                  onClick={addOperatorFilter} 
                  className="btn-secondary"
                >
                  Add Filter
                </button>
              </div>
              
              {operators.length > 0 && (
                <div className="operators-info">
                  <p><strong>Found {operators.length} operators</strong></p>
                </div>
              )}
              
              {operatorFilters.length > 0 && (
                <div className="operator-filters-section">
                  <h4>Operator Filters</h4>
                  <p className="section-description">
                    Filter operators by specific criteria. Multiple filters are combined with AND.
                  </p>
                  {operatorFilters.map(filter => (
                    <div key={filter.id} className="operator-filter-item">
                      <div className="controls-row">
                        <select
                          value={filter.key}
                          onChange={(e) => updateOperatorFilter(filter.id, 'key', e.target.value)}
                        >
                          <option value="">Select Field</option>
                          {operators.length > 0 && operators[0]?.operator && 
                            Object.keys(operators[0].operator)
                              .filter(key => key !== 'ip' && key !== 'port' && key !== 'rest_port' && key !== 'broker_port')
                              .map(key => (
                                <option key={key} value={key}>
                                  {key}
                                </option>
                              ))
                          }
                        </select>
                        <select
                          value={filter.operator}
                          onChange={(e) => updateOperatorFilter(filter.id, 'operator', e.target.value)}
                        >
                          <option value="=">=</option>
                          <option value="!=">!=</option>
                          <option value=">">{'>'}</option>
                          <option value=">=">{'>='}</option>
                          <option value="<">{'<'}</option>
                          <option value="<=">{'<='}</option>
                        </select>
                        <input
                          type="text"
                          value={filter.value}
                          onChange={(e) => updateOperatorFilter(filter.id, 'value', e.target.value)}
                          placeholder="Enter value"
                          className="filter-value-input"
                        />
                        <button 
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            removeOperatorFilter(filter.id);
                          }} 
                          className="btn-remove"
                        >
                          ×
                        </button>
                      </div>
                      {filter.key && filter.operator && filter.value && (
                        <div className="filter-preview">
                          <code>{filter.key} {filter.operator} {isNaN(filter.value) && filter.value !== 'true' && filter.value !== 'false' ? `"${filter.value}"` : filter.value}</code>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
              
              {operatorFilters.length > 0 && (
                <div className="node-selection-preview">
                  <h4>Node Selection Query</h4>
                  <div className="preview-box">
                    <code>{buildNodeSelectionQuery()}</code>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Column Selection */}
        {selectedTable && (
          <div className="columns-panel">
            <div className="columns-header">
              <h3>Column Selection</h3>
              <div className="column-mode-toggle">
                <button 
                  className={`mode-btn ${columnMode === 'columns' ? 'active' : ''}`}
                  onClick={() => handleColumnModeChange('columns')}
                >
                  Select Columns
                </button>
                <button 
                  className={`mode-btn ${columnMode === 'aggregations' ? 'active' : ''}`}
                  onClick={() => handleColumnModeChange('aggregations')}
                >
                  Use Aggregations
                </button>
                <button 
                  className={`mode-btn ${columnMode === 'mixed' ? 'active' : ''}`}
                  onClick={() => handleColumnModeChange('mixed')}
                >
                  Mixed Mode
                </button>
              </div>
            </div>

            {/* GROUP BY Required Warning */}
            {groupByRequired && (
              <div className="group-by-warning">
                <strong>⚠️ Warning:</strong> When using aggregations with non-aggregated columns, a GROUP BY clause is required. Please add GROUP BY columns in the Advanced Options section.
              </div>
            )}

            {/* Column Selection Mode */}
            {(columnMode === 'columns' || columnMode === 'mixed') && (
              <>
                <div className="column-actions">
                  <button onClick={handleSelectAllColumns} className="btn-secondary">
                    Select All
                  </button>
                  <button onClick={handleClearColumns} className="btn-secondary">
                    Clear All
                  </button>
                </div>
                <div className="columns-grid">
                  {columns.map((column, index) => (
                    <div 
                      key={index} 
                      className={`column-item ${selectedColumns.includes(column.column_name || column.name) ? 'selected' : ''}`}
                      onClick={() => handleColumnToggle(column.column_name || column.name)}
                    >
                      <span className="column-name">{column.column_name || column.name}</span>
                      <span className="column-type">{column.data_type || column.type}</span>
                    </div>
                  ))}
                </div>
              </>
            )}

            {/* Separator for Mixed Mode */}
            {columnMode === 'mixed' && (
              <div className="mixed-mode-separator"></div>
            )}

            {/* Aggregations Mode */}
            {(columnMode === 'aggregations' || columnMode === 'mixed') && (
              <div className="aggregations-section">
                <div className="section-header">
                  <h4>Aggregations</h4>
                  <button onClick={addAggregation} className="btn-secondary">Add Aggregation</button>
                </div>
                <p className="section-description">
                  Add aggregation functions as separate columns. Only date/time and numeric columns can be aggregated. You can have multiple aggregations on the same column (e.g., min(timestamp), max(timestamp)). In mixed mode, you can combine regular columns with aggregations.
                </p>
                {columns.filter(col => isAggregatableColumn(col.column_name || col.name)).length === 0 && (
                  <div className="info-message">
                    <strong>ℹ️ Info:</strong> No aggregatable columns found. You can use COUNT(*) to count all rows, or only date/time and numeric columns support other aggregations.
                  </div>
                )}
                {aggregations.map(agg => (
                  <div key={agg.id} className="aggregation-item">
                    <div className="controls-row">
                      <select
                        value={agg.function}
                        onChange={(e) => updateAggregation(agg.id, 'function', e.target.value)}
                      >
                        {agg.column === '*' ? (
                          <>
                            <option value="COUNT">COUNT</option>
                          </>
                        ) : isDateColumn(agg.column) ? (
                          <>
                            <option value="MIN">MIN (Date/Time)</option>
                            <option value="MAX">MAX (Date/Time)</option>
                          </>
                        ) : (
                          <>
                            <option value="COUNT">COUNT</option>
                            <option value="SUM">SUM</option>
                            <option value="AVG">AVG</option>
                            <option value="MIN">MIN</option>
                            <option value="MAX">MAX</option>
                          </>
                        )}
                      </select>
                      <select
                        value={agg.column}
                        onChange={(e) => updateAggregation(agg.id, 'column', e.target.value)}
                      >
                        <option value="">Select Column</option>
                        <option value="*">* (Count All)</option>
                        {columns
                          .filter(col => isAggregatableColumn(col.column_name || col.name))
                          .map(col => (
                            <option key={col.column_name || col.name} value={col.column_name || col.name}>
                              {col.column_name || col.name} ({col.data_type || col.type})
                            </option>
                          ))}
                      </select>
                      <input
                        type="text"
                        value={agg.alias}
                        onChange={(e) => updateAggregation(agg.id, 'alias', e.target.value)}
                        placeholder="Alias (optional)"
                      />
                      <button 
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          removeAggregation(agg.id);
                        }} 
                        className="btn-remove"
                      >
                        ×
                      </button>
                    </div>
                    {(agg.function && (agg.column || agg.column === '*')) && (
                      <div className="aggregation-preview">
                        <code>{getAggregationPreview(agg)}</code>
                        {agg.column !== '*' && isDateColumn(agg.column) && agg.function !== 'MIN' && agg.function !== 'MAX' && (
                          <div className="warning-message">
                            <strong>⚠️ Warning:</strong> Date/time columns only support MIN and MAX functions.
                          </div>
                        )}
                        {agg.column !== '*' && !isAggregatableColumn(agg.column) && (
                          <div className="error-message">
                            <strong>❌ Error:</strong> This column type does not support aggregations. Only date/time and numeric columns can be aggregated.
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* AnyLog Query Options */}
        <div className="query-options-panel">
          <h3>AnyLog Query Options</h3>
          <div className="options-grid">
            <div className="option-group">
              <label>Format:</label>
              <select value={format} onChange={(e) => setFormat(e.target.value)}>
                <option value="json">JSON</option>
                <option value="table">Table</option>
                {/* <option value="csv">CSV</option>
                <option value="xml">XML</option> */}
              </select>
            </div>
            
            <div className="option-group">
              <label>Timezone:</label>
              <select value={timezone} onChange={(e) => setTimezone(e.target.value)}>
                <option value="utc">UTC</option>
                <option value="local">Local (AnyLog Node)</option>
                <option value="pt">Pacific Time</option>
                <option value="mt">Mountain Time</option>
                <option value="ct">Central Time</option>
                <option value="et">Eastern Time</option>
              </select>
            </div>
            
            {/* <div className="option-group">
              <label>
                <input
                  type="checkbox"
                  checked={distinct}
                  onChange={(e) => setDistinct(e.target.checked)}
                />
                DISTINCT
              </label>
            </div> */}
          </div>
        </div>

        {/* Time-Series Analysis */}
        <div className="increments-panel">
          <div className="time-series-header">
            <h3>Time-Series Analysis</h3>
            <div className="time-series-mode-toggle">
              <button 
                className={`mode-btn ${timeSeriesMode === 'none' ? 'active' : ''}`}
                onClick={() => handleTimeSeriesModeChange('none')}
              >
                None
              </button>
              <button 
                className={`mode-btn ${timeSeriesMode === 'increments' ? 'active' : ''}`}
                onClick={() => handleTimeSeriesModeChange('increments')}
              >
                Increments
              </button>
              <button 
                className={`mode-btn ${timeSeriesMode === 'periods' ? 'active' : ''}`}
                onClick={() => handleTimeSeriesModeChange('periods')}
              >
                Periods
              </button>
            </div>
          </div>

          {/* Increments Mode */}
          {timeSeriesMode === 'increments' && (
            <div className="increments-controls">
              <div className="increments-config">
                <div className="option-group">
                  <label>Time Unit:</label>
                  <select value={incrementsUnit} onChange={(e) => setIncrementsUnit(e.target.value)}>
                    <option value="second">Second</option>
                    <option value="minute">Minute</option>
                    <option value="hour">Hour</option>
                    <option value="day">Day</option>
                    <option value="week">Week</option>
                    <option value="month">Month</option>
                    <option value="year">Year</option>
                  </select>
                </div>
                
                <div className="option-group">
                  <label>Interval:</label>
                  <input
                    type="number"
                    value={incrementsInterval}
                    onChange={(e) => setIncrementsInterval(parseInt(e.target.value) || 1)}
                    placeholder="e.g., 5"
                    min="1"
                  />
                </div>
                
                <div className="option-group">
                  <label>Date/Time Column:</label>
                  <select 
                    value={incrementsDateColumn} 
                    onChange={(e) => setIncrementsDateColumn(e.target.value)}
                    disabled={!selectedTable}
                  >
                    <option value="">Select Date Column</option>
                    {columns
                      .filter(col => {
                        const type = (col.data_type || col.type || '').toLowerCase();
                        return type.includes('date') || type.includes('time') || type.includes('timestamp');
                      })
                      .map((col, index) => (
                        <option key={index} value={col.column_name || col.name}>
                          {col.column_name || col.name} ({col.data_type || col.type})
                        </option>
                      ))}
                  </select>
                </div>
                
                <div className="increments-info">
                  <p><strong>Function:</strong> <code>increments({incrementsUnit || 'minute'}, {incrementsInterval}, {incrementsDateColumn || 'date_column'})</code></p>
                  <p><em>Creates time buckets for time-series analysis. Automatically adds min() and max() of the selected date column.</em></p>
                  {timeSeriesMode === 'increments' && aggregations.length === 0 && (
                    <p className="warning-message">
                      <strong>⚠️ Warning:</strong> Increments requires at least one aggregated column. Please add an aggregation above.
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Periods Mode */}
          {timeSeriesMode === 'periods' && (
            <div className="periods-section">
              <div className="section-header">
                <h4>Period Conditions</h4>
                <button onClick={addPeriod} className="btn-secondary">Add Period</button>
              </div>
              <p className="section-description">
                Add period conditions for time-based filtering. Periods are combined with WHERE conditions using AND.
              </p>
              {periods.map(period => (
                <div key={period.id} className="period-item">
                  <div className="controls-row">
                    <select
                      value={period.timeScale}
                      onChange={(e) => updatePeriod(period.id, 'timeScale', e.target.value)}
                    >
                      <option value="second">Second</option>
                      <option value="minute">Minute</option>
                      <option value="hour">Hour</option>
                      <option value="day">Day</option>
                      <option value="week">Week</option>
                      <option value="month">Month</option>
                      <option value="year">Year</option>
                    </select>
                    <input
                      type="number"
                      value={period.amount}
                      onChange={(e) => updatePeriod(period.id, 'amount', parseInt(e.target.value) || 1)}
                      placeholder="Amount"
                      min="1"
                      style={{ maxWidth: '100px' }}
                    />
                    <div className="value-input-group">
                      <input
                        type="text"
                        value={period.startValue}
                        onChange={(e) => updatePeriod(period.id, 'startValue', e.target.value)}
                        placeholder="Start value (e.g., NOW(), '2024-01-01')"
                      />
                      <button
                        type="button"
                        onClick={() => setPeriodNowValue(period.id)}
                        className="btn-now"
                        title="Set to NOW()"
                      >
                        NOW()
                      </button>
                    </div>
                    <select
                      value={period.column}
                      onChange={(e) => updatePeriod(period.id, 'column', e.target.value)}
                    >
                      <option value="">Select Date Column</option>
                      {columns
                        .filter(col => isDateColumn(col.column_name || col.name))
                        .map(col => (
                          <option key={col.column_name || col.name} value={col.column_name || col.name}>
                            {col.column_name || col.name} ({col.data_type || col.type})
                          </option>
                        ))}
                    </select>
                    <button 
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        removePeriod(period.id);
                      }} 
                      className="btn-remove"
                    >
                      ×
                    </button>
                  </div>
                  {period.timeScale && period.amount && period.startValue && period.column && (
                    <div className="period-preview">
                      <code>{getPeriodPreview(period)}</code>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Advanced Options */}
        <div className="advanced-panel">
          <button 
            className="toggle-advanced"
            onClick={() => setShowAdvanced(!showAdvanced)}
          >
            {showAdvanced ? 'Hide' : 'Show'} Advanced Options
          </button>
          
          {showAdvanced && (
            <div className="advanced-options">
              <div className="where-section">
                <div className="section-header">
                  <h4>WHERE Conditions</h4>
                  <button onClick={addWhereCondition} className="btn-secondary">Add Condition</button>
                </div>
                <p className="section-description">
                  Add filtering conditions to your query. Multiple conditions can be combined with AND or OR operators.
                </p>
                {whereConditions.map(condition => (
                  <div key={condition.id} className="where-condition-item">
                    <div className="controls-row">
                      <select
                        value={condition.column}
                        onChange={(e) => updateWhereCondition(condition.id, 'column', e.target.value)}
                      >
                        <option value="">Select Column</option>
                        {columns.map(col => (
                          <option key={col.column_name || col.name} value={col.column_name || col.name}>
                            {col.column_name || col.name} ({col.data_type || col.type})
                          </option>
                        ))}
                      </select>
                      <select
                        value={condition.operator}
                        onChange={(e) => updateWhereCondition(condition.id, 'operator', e.target.value)}
                      >
                        <option value="=">=</option>
                        <option value="!=">!=</option>
                        <option value=">">{'>'}</option>
                        <option value=">=">{'>='}</option>
                        <option value="<">{'<'}</option>
                        <option value="<=">{'<='}</option>
                      </select>
                      <div className="value-input-group">
                        <input
                          type="text"
                          value={condition.value}
                          onChange={(e) => updateWhereCondition(condition.id, 'value', e.target.value)}
                          placeholder="Enter value"
                        />
                        {isDateColumn(condition.column) && (
                          <button
                            type="button"
                            onClick={() => setNowValue(condition.id)}
                            className="btn-now"
                            title="Set to NOW()"
                          >
                            NOW()
                          </button>
                        )}
                      </div>
                      {whereConditions.length > 1 && (
                        <select
                          value={condition.logicalOperator || 'AND'}
                          onChange={(e) => updateWhereCondition(condition.id, 'logicalOperator', e.target.value)}
                          className="logical-operator-select"
                        >
                          <option value="AND">AND</option>
                          <option value="OR">OR</option>
                        </select>
                      )}
                      <button 
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          removeWhereCondition(condition.id);
                        }} 
                        className="btn-remove"
                      >
                        ×
                      </button>
                    </div>
                    {condition.column && condition.operator && condition.value && (
                      <div className="where-preview">
                        <code>
                          {whereConditions.length > 1 && whereConditions.indexOf(condition) > 0 && (
                            <span className="logical-operator">{condition.logicalOperator || 'AND'} </span>
                          )}
                          {condition.column} {condition.operator} {condition.value === 'NOW()' ? 'NOW()' : `'${condition.value}'`}
                        </code>
                      </div>
                    )}
                  </div>
                ))}
              </div>
              
              <div className="include-section">
                <div className="section-header">
                  <h4>Include Tables</h4>
                  <button onClick={addIncludeTable} className="btn-secondary">Add Table</button>
                </div>
                <p className="section-description">
                  Include additional tables in your query. Use <code>db_name.table_name</code> format for cross-database tables.
                </p>
                {includeTables.map(table => (
                  <div key={table.id} className="include-table-item">
                    <div className="controls-row">
                      <input
                        type="text"
                        value={table.tableName}
                        onChange={(e) => updateIncludeTable(table.id, 'tableName', e.target.value)}
                        placeholder="e.g., wp_analog, wp_digital, db_name.table_name"
                        className="table-name-input"
                      />
                      <button 
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          removeIncludeTable(table.id);
                        }} 
                        className="btn-remove"
                      >
                        ×
                      </button>
                    </div>
                    {table.tableName && (
                      <div className="include-preview">
                        <code>{table.tableName}</code>
                      </div>
                    )}
                  </div>
                ))}
              </div>
              
              <div className="extend-section">
                <div className="section-header">
                  <h4>Extend Fields</h4>
                  <div className="extend-actions">
                    <button onClick={populateDefaultExtendFields} className="btn-secondary">Use Defaults</button>
                    <button onClick={addExtendField} className="btn-secondary">Add Field</button>
                  </div>
                </div>
                <p className="section-description">
                  Add additional fields to your query. Use the "Use Defaults" button to populate common fields like +ip, +overlay_ip, +hostname, and @table_name.
                </p>
                {extendFields.map(field => (
                  <div key={field.id} className="extend-field-item">
                    <div className="controls-row">
                      <input
                        type="text"
                        value={field.fieldName}
                        onChange={(e) => updateExtendField(field.id, 'fieldName', e.target.value)}
                        placeholder="e.g., +ip, +overlay_ip, +hostname, @table_name"
                        className="field-name-input"
                      />
                      <button 
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          removeExtendField(field.id);
                        }} 
                        className="btn-remove"
                      >
                        ×
                      </button>
                    </div>
                    {field.fieldName && (
                      <div className="extend-preview">
                        <code>{field.fieldName}</code>
                      </div>
                    )}
                  </div>
                ))}
              </div>
              
              <div className="group-by-section">
                <div className="section-header">
                  <h4>GROUP BY</h4>
                  <div className="group-by-actions">
                    <button onClick={handleSelectAllGroupByColumns} className="btn-secondary">Select All</button>
                    <button onClick={handleClearGroupByColumns} className="btn-secondary">Clear All</button>
                  </div>
                </div>
                <p className="section-description">
                  Group your results by selected columns. This is useful when using aggregations to group data by specific fields. <strong>Note:</strong> When using aggregations with non-aggregated columns, GROUP BY is required.
                </p>
                <div className="group-by-columns-grid">
                  {columns.map((column, index) => (
                    <div 
                      key={index} 
                      className={`group-by-column-item ${groupByColumns.includes(column.column_name || column.name) ? 'selected' : ''}`}
                      onClick={() => handleGroupByColumnToggle(column.column_name || column.name)}
                    >
                      <span className="column-name">{column.column_name || column.name}</span>
                      <span className="column-type">{column.data_type || column.type}</span>
                    </div>
                  ))}
                </div>
                {groupByColumns.length > 0 && (
                  <div className="group-by-preview">
                    <code>GROUP BY {groupByColumns.join(', ')}</code>
                  </div>
                )}
              </div>
              
              <div className="order-by-section">
                <div className="section-header">
                  <h4>ORDER BY</h4>
                  <div className="order-by-actions">
                    <button onClick={handleSelectAllOrderByColumns} className="btn-secondary">Select All</button>
                    <button onClick={handleClearOrderByColumns} className="btn-secondary">Clear All</button>
                  </div>
                </div>
                <p className="section-description">
                  Order your results by selected columns. You can specify ascending (ASC) or descending (DESC) order for each column.
                </p>
                <div className="order-by-columns-grid">
                  {columns.map((column, index) => {
                    const isSelected = orderByColumns.some(col => col.column === (column.column_name || column.name));
                    const selectedColumn = orderByColumns.find(col => col.column === (column.column_name || column.name));
                    return (
                      <div 
                        key={index} 
                        className={`order-by-column-item ${isSelected ? 'selected' : ''}`}
                        onClick={() => handleOrderByColumnToggle(column.column_name || column.name)}
                      >
                        <span className="column-name">{column.column_name || column.name}</span>
                        <span className="column-type">{column.data_type || column.type}</span>
                        {isSelected && (
                          <div className="direction-buttons">
                            <button
                              className={`direction-btn ${selectedColumn.direction === 'ASC' ? 'active' : ''}`}
                              onClick={(e) => {
                                e.stopPropagation();
                                handleOrderByDirectionChange(column.column_name || column.name, 'ASC');
                              }}
                              title="Ascending"
                            >
                              ↑
                            </button>
                            <button
                              className={`direction-btn ${selectedColumn.direction === 'DESC' ? 'active' : ''}`}
                              onClick={(e) => {
                                e.stopPropagation();
                                handleOrderByDirectionChange(column.column_name || column.name, 'DESC');
                              }}
                              title="Descending"
                            >
                              ↓
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
                {orderByColumns.length > 0 && (
                  <div className="order-by-preview">
                    <code>ORDER BY {orderByColumns.map(col => `${col.column} ${col.direction}`).join(', ')}</code>
                  </div>
                )}
              </div>
              
              <div className="option-group">
                <label>LIMIT:</label>
                <input
                  type="number"
                  value={limit}
                  onChange={(e) => setLimit(e.target.value)}
                  placeholder="e.g., 100"
                  min="1"
                />
              </div>

              {/* <div className="joins-section">
                <div className="section-header">
                  <h4>JOINs</h4>
                  <button onClick={addJoin} className="btn-secondary">Add JOIN</button>
                </div>
                {joins.map(join => (
                  <div key={join.id} className="join-item">
                    <select
                      value={join.type}
                      onChange={(e) => updateJoin(join.id, 'type', e.target.value)}
                    >
                      <option value="INNER">INNER JOIN</option>
                      <option value="LEFT">LEFT JOIN</option>
                      <option value="RIGHT">RIGHT JOIN</option>
                      <option value="FULL">FULL JOIN</option>
                    </select>
                    <input
                      type="text"
                      value={join.table}
                      onChange={(e) => updateJoin(join.id, 'table', e.target.value)}
                      placeholder="Table name"
                    />
                    <input
                      type="text"
                      value={join.condition}
                      onChange={(e) => updateJoin(join.id, 'condition', e.target.value)}
                      placeholder="ON condition"
                    />
                    <button 
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        removeJoin(join.id);
                      }} 
                      className="btn-remove"
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div> */}
            </div>
          )}
        </div>

        {/* Generated Query */}
        <div className="query-panel">
          <h3>Generated AnyLog Query</h3>
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Select columns and options to generate a query..."
            rows={8}
            className="query-textarea"
            readOnly
          />
          <div className="query-actions">
            <button 
              onClick={copyQuery} 
              disabled={!query.trim()}
              className="btn-primary"
            >
              Copy Query
            </button>
            <button 
              onClick={executeQuery} 
              disabled={!query.trim() || executing}
              className="btn-execute"
            >
              {executing ? (
                <>
                  <span className="spinner">⏳</span> Executing...
                </>
              ) : (
                'Execute Query'
              )}
            </button>
            <button onClick={clearQuery} className="btn-secondary">
              Clear Query
            </button>
          </div>
        </div>

        {/* Execution Results */}
        {executionError && (
          <div className="execution-error">
            <h3>Execution Error</h3>
            <div className="error-content">
              <strong>Error:</strong> {executionError}
            </div>
          </div>
        )}

        {executionResult && (
          <div className="execution-results">
            <h3>Query Results</h3>
            {executionTime && (
              <p className="execution-time">
                <strong>Execution Time:</strong> {executionTime}ms
              </p>
            )}
            <div className="results-content">
              {executionResult.type === 'table' && (
                <div className="table-results">
                  <p><strong>Type:</strong> Table Data</p>
                  <p><strong>Rows:</strong> {executionResult.data ? executionResult.data.length : 0}</p>
                  {executionResult.data && executionResult.data.length > 0 && executionResult.data[0] && (
                    <p><strong>Columns:</strong> {Object.keys(executionResult.data[0]).length}</p>
                  )}
                  {executionResult.data && executionResult.data.length > 0 && executionResult.data[0] ? (
                    <div className="table-container">
                      <DataTable data={executionResult.data} />
                    </div>
                  ) : (
                    <div className="no-data-message">
                      <p>No data returned from query.</p>
                    </div>
                  )}
                  {additionalContent && (
                    <div className="additional-content">
                      <h4>Additional Information</h4>
                      <pre className="additional-content-text">{additionalContent}</pre>
                    </div>
                  )}
                </div>
              )}
              {executionResult.type === 'json' && (
                <div className="json-results">
                  <p><strong>Type:</strong> JSON Response</p>
                  <pre className="results-json">
                    {JSON.stringify(executionResult.data, null, 2)}
                  </pre>
                </div>
              )}
              {executionResult.type === 'blobs' && (
                <div className="blob-results">
                  <p><strong>Type:</strong> Blob Data</p>
                  <p><strong>Blobs:</strong> {executionResult.data ? executionResult.data.length : 0}</p>
                  <pre className="results-json">
                    {JSON.stringify(executionResult.data, null, 2)}
                  </pre>
                </div>
              )}
              {!executionResult.type && (
                <div className="string-results">
                  <p><strong>Type:</strong> String Response</p>
                  <pre className="results-text">
                    {executionResult.data}
                  </pre>
                </div>
              )}
            </div>
            <div className="results-actions">
              <button onClick={clearResults} className="btn-secondary">
                Clear Results
              </button>
            </div>
          </div>
        )}

        {/* Error Display */}
        {error && (
          <div className="error-message">
            <strong>Error:</strong> {error}
          </div>
        )}
      </div>
    </div>
  );
};

export default SqlQueryGenerator; 
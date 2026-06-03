import React, { useState } from 'react';
import { calculate } from './calculator_api';

const CalculatorPage = () => {
  const [operation, setOperation] = useState('add');
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const getOperationSymbol = (op) => {
    switch (op) {
      case 'add': return '+';
      case 'subtract': return '-';
      case 'multiply': return '×';
      case 'divide': return '÷';
      default: return op;
    }
  };

  const handleCalculate = async () => {
    // Validate inputs
    if (!a || !b) {
      setResult({ error: 'Please enter both numbers' });
      return;
    }

    const numA = parseFloat(a);
    const numB = parseFloat(b);
    
    if (isNaN(numA) || isNaN(numB)) {
      setResult({ error: 'Please enter valid numbers' });
      return;
    }

    setLoading(true);
    setResult(null);
    try {
      const data = await calculate({
        operation,
        a: numA,
        b: numB
      });
      setResult(data);
    } catch (error) {
      console.error('Calculation error:', error);
      setResult({ error: error.message || 'Failed to calculate' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: '20px', maxWidth: '600px', margin: '0 auto' }}>
      <h1>🧮 Calculator Plugin</h1>
      <p>Simple calculator plugin demonstrating the automatic plugin system!</p>
      
      {/* Calculator Form */}
      <div style={{ 
        backgroundColor: '#f8f9fa', 
        padding: '20px', 
        borderRadius: '8px', 
        marginBottom: '30px' 
      }}>
        <h3>Calculator</h3>
        
        <div style={{ marginBottom: '15px' }}>
          <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
            Operation:
          </label>
          <select 
            value={operation} 
            onChange={(e) => setOperation(e.target.value)}
            style={{ 
              width: '100%', 
              padding: '8px', 
              border: '1px solid #ced4da', 
              borderRadius: '4px' 
            }}
          >
            <option value="add">Add (+)</option>
            <option value="subtract">Subtract (-)</option>
            <option value="multiply">Multiply (×)</option>
            <option value="divide">Divide (÷)</option>
          </select>
        </div>
        
        <div style={{ marginBottom: '15px' }}>
          <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
            First Number:
          </label>
          <input 
            type="number" 
            value={a} 
            onChange={(e) => setA(e.target.value)}
            placeholder="Enter first number"
            style={{ 
              width: '100%', 
              padding: '8px', 
              border: '1px solid #ced4da', 
              borderRadius: '4px' 
            }}
          />
        </div>
        
        <div style={{ marginBottom: '15px' }}>
          <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
            Second Number:
          </label>
          <input 
            type="number" 
            value={b} 
            onChange={(e) => setB(e.target.value)}
            placeholder="Enter second number"
            style={{ 
              width: '100%', 
              padding: '8px', 
              border: '1px solid #ced4da', 
              borderRadius: '4px' 
            }}
          />
        </div>
        
        <button 
          onClick={handleCalculate} 
          disabled={loading}
          style={{ 
            padding: '10px 20px', 
            fontSize: '16px',
            backgroundColor: '#007bff',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: loading ? 'not-allowed' : 'pointer',
            opacity: loading ? 0.6 : 1
          }}
        >
          {loading ? 'Calculating...' : 'Calculate'}
        </button>
      </div>
      
      {result && (
        <div style={{ 
          marginTop: '20px', 
          padding: '15px', 
          backgroundColor: result.error ? '#f8d7da' : '#d4edda',
          borderRadius: '5px',
          border: `1px solid ${result.error ? '#f5c6cb' : '#c3e6cb'}`
        }}>
          {result.error ? (
            <div>
              <h3 style={{ color: '#721c24', margin: '0 0 10px 0' }}>❌ Error</h3>
              <p style={{ color: '#721c24', margin: 0 }}>{result.error}</p>
            </div>
          ) : (
            <div>
              <h3 style={{ color: '#155724', margin: '0 0 10px 0' }}>✅ Result</h3>
              <p style={{ color: '#155724', margin: 0, fontSize: '18px' }}>
                {result.a} {getOperationSymbol(result.operation)} {result.b} = <strong>{result.result}</strong>
              </p>
            </div>
          )}
        </div>
      )}

      {/* Plugin Info */}
      <div style={{ 
        marginTop: '30px', 
        padding: '15px', 
        backgroundColor: '#fff3cd', 
        borderRadius: '8px',
        border: '1px solid #ffeaa7'
      }}>
        <h4>🧮 Calculator Plugin Info</h4>
        <p style={{ margin: '5px 0', fontSize: '14px' }}>
          This plugin demonstrates:
        </p>
        <ul style={{ margin: '5px 0', fontSize: '14px' }}>
          <li>Simple API integration</li>
          <li>Error handling and validation</li>
          <li>Clean form UI</li>
          <li>Real-time calculation results</li>
        </ul>
      </div>
    </div>
  );
};

// Plugin metadata - used by the plugin loader
export const pluginMetadata = {
  name: 'Calculator',
  icon: '🧮'
};

export default CalculatorPage;

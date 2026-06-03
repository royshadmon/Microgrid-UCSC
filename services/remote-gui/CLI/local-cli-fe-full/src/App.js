import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import './styles/App.css'; // Import your global styles here

// npm i -D react-router-dom ------> NEED TO INSTALL REACT-ROUTER-DOM TO WORK PROPERLY
function App() {
  return (
    <Router>
      <Routes>
        {/* Protected Dashboard Route */}
        <Route
          path="/dashboard/*"
          element={<Dashboard />}
        />
        {/* Default Route */}
        <Route path="*" element={<Navigate to="/dashboard/client" />} />
      </Routes>
    </Router>
  );
}

export default App;

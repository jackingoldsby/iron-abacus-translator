import React from 'react';
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import WorkListPage from './pages/WorkListPage';
import JobsPage from './pages/JobsPage';
import AllJobsPage from './pages/AllJobsPage';
import WorkflowsPage from './pages/WorkflowsPage';
import ConfigPage from './pages/ConfigPage';
import DAGPipelinePage from './pages/DAGPipelinePage';
import { ToastContainer } from './components/Toast';

function App() {
  return (
    <BrowserRouter>
      <ToastContainer />
      <div className="app">
        <header className="header">
          <div className="container">
            <h1>Translation Manager</h1>
            <p>Book Processing Toolkit - Translation Management Interface</p>
            <nav style={{ marginTop: '15px' }}>
              <Link to="/" style={linkStyle}>📚 Works Catalog</Link>
              {' | '}
              <Link to="/pipeline" style={linkStyle}>🔀 DAG Pipeline</Link>
              {' | '}
              <Link to="/workflows" style={linkStyle}>⚙️ Workflows</Link>
              {' | '}
              <Link to="/jobs/all" style={linkStyle}>📊 Job Monitor</Link>
              {' | '}
              <Link to="/config" style={linkStyle}>🔧 Configuration</Link>
            </nav>
          </div>
        </header>

        <div className="container">
          <Routes>
            <Route path="/" element={<WorkListPage />} />
            <Route path="/pipeline" element={<DAGPipelinePage />} />
            <Route path="/workflows" element={<WorkflowsPage />} />
            <Route path="/jobs" element={<JobsPage />} />
            <Route path="/jobs/all" element={<AllJobsPage />} />
            <Route path="/config" element={<ConfigPage />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}

const linkStyle = {
  color: '#3498db',
  textDecoration: 'none',
  fontWeight: 500,
  padding: '5px 10px',
};

export default App;

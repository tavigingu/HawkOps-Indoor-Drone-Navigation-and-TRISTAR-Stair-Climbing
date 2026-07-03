import React, { useState } from 'react';
import LandingPage from './pages/LandingPage';
import DroneConsole from './pages/DroneConsole';
import RoomReportPage from './pages/RoomReportPage';

export default function App() {
  const [view, setView] = useState('landing');

  // standalone report route, e.g. /report/2
  const reportMatch = window.location.pathname.match(/^\/report\/(\d+)$/);
  if (reportMatch) {
    return (
      <div className="app-shell" style={{ padding: '90px 6vw', minHeight: '100vh' }}>
        <RoomReportPage roomIndex={Number(reportMatch[1])} />
      </div>
    );
  }

  if (view === 'console') {
    return <DroneConsole onExit={() => setView('landing')} />;
  }

  return <LandingPage onStartMission={() => setView('console')} />;
}

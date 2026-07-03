import React, { useState, useEffect } from 'react';

// Focus brackets that frame the drone the moment a connection lands.
function FocusBrackets({ isConnected }) {
  const [showBrackets, setShowBrackets] = useState(false);
  const [isFocused, setIsFocused] = useState(false);
  const [isFadingOut, setIsFadingOut] = useState(false);
  const [wasConnected, setWasConnected] = useState(false);

  useEffect(() => {
    if (isConnected && !wasConnected) {
      setShowBrackets(true);
      setIsFocused(false);
      setIsFadingOut(false);
      const focusTimer = setTimeout(() => setIsFocused(true), 50);
      const fadeTimer = setTimeout(() => setIsFadingOut(true), 1800);
      const hideTimer = setTimeout(() => {
        setShowBrackets(false);
        setIsFocused(false);
        setIsFadingOut(false);
      }, 2800);
      return () => {
        clearTimeout(focusTimer);
        clearTimeout(fadeTimer);
        clearTimeout(hideTimer);
      };
    }
    setWasConnected(isConnected);
  }, [isConnected, wasConnected]);

  if (!showBrackets) return null;

  return (
    <div
      className="focus-corners"
      style={{
        opacity: isFadingOut ? 0 : 1,
        transform: isFocused
          ? 'translate(-50%, -50%) scale(1)'
          : 'translate(-50%, -50%) scale(2.5)',
        transition: isFadingOut
          ? 'opacity 1s ease-out, transform 1s ease-out'
          : 'opacity 0.3s ease-in-out, transform 1.2s cubic-bezier(0.34, 1.56, 0.64, 1)',
      }}
    >
      <div className="corner corner-tl" />
      <div className="corner corner-tr" />
      <div className="corner corner-bl" />
      <div className="corner corner-br" />
    </div>
  );
}

export default function HUD({ isActive = true, droneData, isConnected = false }) {
  const [time, setTime] = useState(new Date().toLocaleTimeString());

  useEffect(() => {
    const interval = setInterval(() => setTime(new Date().toLocaleTimeString()), 1000);
    return () => clearInterval(interval);
  }, []);

  if (!isActive) return null;

  const {
    battery = 0,
    altitude = 0,
    is_flying = false,
    attitude = { pitch: 0, roll: 0, yaw: 0 },
    speed = { vx: 0, vy: 0, vz: 0 },
    position = { x: 0, y: 0, z: 0 },
    max_altitude = 30,
  } = droneData || {};

  const status = isConnected ? (is_flying ? 'FLYING' : 'LINKED') : 'STANDBY';
  const totalSpeed = Math.sqrt(
    Math.pow(speed.vx || 0, 2) + Math.pow(speed.vy || 0, 2) + Math.pow(speed.vz || 0, 2)
  ).toFixed(1);
  const gpsStatus = position.x !== 0 || position.y !== 0 ? 'LOCKED' : 'SEARCH';

  const accent = '#2fe38b';
  const statusColor = isConnected ? accent : '#ff5a6a';
  const batteryColor = battery > 60 ? accent : battery > 30 ? '#ffb74d' : '#ff5a6a';

  return (
    <div className="hud-overlay">
      <div className="hud-panel top-left">
        <div className="hud-key" style={{ color: statusColor }}>
          <span className="hud-led" style={{ background: statusColor, boxShadow: `0 0 10px ${statusColor}` }} />
          {status}
        </div>
        <div className="hud-bar">
          <div className="hud-fill" style={{ width: `${battery}%`, background: batteryColor }} />
        </div>
        <div className="hud-row"><span>BATTERY</span><span>{battery.toFixed(0)}%</span></div>
        <div className="hud-row"><span>MODE</span><span>{is_flying ? 'AIRBORNE' : 'GROUNDED'}</span></div>
      </div>

      <div className="hud-panel top-right">
        <div className="hud-row"><span>ALT</span><span>{altitude.toFixed(1)}m</span></div>
        <div className="hud-row"><span>GPS</span><span>{gpsStatus}</span></div>
        <div className="hud-row"><span>SPD</span><span>{totalSpeed} m/s</span></div>
        <div className="hud-row"><span>CEIL</span><span>{max_altitude}m</span></div>
        <div className="hud-row sub"><span>UTC</span><span>{time}</span></div>
      </div>

      <div className="hud-panel bottom-left">
        <div className="hud-title">TELEMETRY</div>
        <div className="hud-row"><span>POS X</span><span>{position.x.toFixed(1)}m</span></div>
        <div className="hud-row"><span>POS Y</span><span>{position.y.toFixed(1)}m</span></div>
        <div className="hud-row"><span>POS Z</span><span>{position.z.toFixed(1)}m</span></div>
      </div>

      <div className="hud-panel bottom-right compass-panel">
        <div className="hud-compass">
          <div className="compass-ring" style={{ transform: `rotate(${attitude.yaw || 0}deg)` }}>
            <div className="compass-needle" />
          </div>
          <div className="hud-row sub" style={{ justifyContent: 'center' }}>
            HDG {Math.abs(Math.round(attitude.yaw || 0)).toString().padStart(3, '0')}°
          </div>
        </div>
        <div className="hud-row"><span>PITCH</span><span>{(attitude.pitch || 0).toFixed(1)}°</span></div>
        <div className="hud-row"><span>ROLL</span><span>{(attitude.roll || 0).toFixed(1)}°</span></div>
      </div>

      <div className="hud-center">
        <div className="crosshair">
          <div className="crosshair-h" style={{ background: statusColor, boxShadow: `0 0 10px ${statusColor}` }} />
          <div className="crosshair-v" style={{ background: statusColor, boxShadow: `0 0 10px ${statusColor}` }} />
          <div
            className="target-ring"
            style={{
              borderColor: isConnected ? 'rgba(47,227,139,0.85)' : 'rgba(255,90,106,0.8)',
              transform: isConnected ? 'translate(-50%, -50%) scale(1)' : 'translate(-50%, -50%) scale(2.5)',
              opacity: isConnected ? 1 : 0.6,
              transition: 'border-color 1.2s ease-in-out, transform 1.2s cubic-bezier(0.34,1.56,0.64,1), opacity 1.2s ease-in-out',
            }}
          >
            <div className="target-dot" style={{ background: statusColor, boxShadow: `0 0 10px ${statusColor}` }} />
          </div>
          <div
            className="target-ring-outer"
            style={{
              borderColor: 'rgba(255,90,106,0.35)',
              animation: !isConnected ? 'outerRingPulse 2s ease-in-out infinite' : 'none',
              opacity: isConnected ? 0 : 1,
              transform: isConnected ? 'translate(-50%, -50%) scale(0.8)' : 'translate(-50%, -50%) scale(1)',
              transition: 'opacity 1.2s ease-out, transform 1.2s ease-out',
            }}
          />
          <FocusBrackets isConnected={isConnected} />
        </div>

        {isConnected && (
          <div className="scan-lines">
            <div className="scan-line" />
            <div className="scan-line" />
            <div className="scan-line" />
          </div>
        )}
      </div>

      <style>{`
        .hud-overlay {
          position: absolute; inset: 0;
          pointer-events: none; z-index: 10;
          font-family: var(--font-mono);
        }
        .hud-panel {
          position: absolute;
          background: rgba(10, 16, 14, 0.42);
          border: 1px solid rgba(47, 227, 139, 0.22);
          padding: 12px 14px;
          font-size: 0.72rem;
          backdrop-filter: blur(14px) saturate(140%);
          -webkit-backdrop-filter: blur(14px) saturate(140%);
          border-radius: 14px;
          box-shadow: 0 10px 30px -12px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.05);
          min-width: 158px;
        }
        .top-left { top: 22px; left: 22px; }
        .top-right { top: 22px; right: 22px; }
        .bottom-left { bottom: 22px; left: 22px; }
        .bottom-right { bottom: 22px; right: 22px; }
        .hud-key {
          display: flex; align-items: center; gap: 8px;
          font-weight: 600; letter-spacing: 2px; font-size: 0.8rem;
          margin-bottom: 10px;
        }
        .hud-led { width: 8px; height: 8px; border-radius: 50%; animation: dotPulse 2s ease-in-out infinite; }
        .hud-title { color: var(--accent); letter-spacing: 2px; margin-bottom: 8px; font-size: 0.72rem; opacity: 0.9; }
        .hud-row {
          display: flex; justify-content: space-between; gap: 14px;
          color: #cfe9dc; letter-spacing: 1px; margin: 4px 0;
        }
        .hud-row span:first-child { color: var(--text-faint); }
        .hud-row span:last-child { color: #e8fff4; }
        .hud-row.sub { opacity: 0.7; font-size: 0.66rem; margin-top: 8px; }
        .hud-bar {
          width: 100%; height: 6px; background: rgba(47,227,139,0.12);
          margin: 6px 0 8px; border-radius: 3px; overflow: hidden;
        }
        .hud-fill { height: 100%; border-radius: 3px; transition: width 0.5s ease; box-shadow: 0 0 10px rgba(47,227,139,0.5); }

        .compass-panel { text-align: left; }
        .hud-compass { display: flex; flex-direction: column; align-items: center; gap: 6px; margin-bottom: 8px; }
        .compass-ring {
          width: 42px; height: 42px; border: 2px solid var(--accent);
          border-radius: 50%; position: relative; transition: transform 0.3s ease;
          box-shadow: 0 0 14px rgba(47,227,139,0.3);
        }
        .compass-needle {
          position: absolute; top: 2px; left: 50%; transform: translateX(-50%);
          width: 2px; height: 17px; background: #ff5a6a; border-radius: 1px;
        }
        .hud-center {
          position: absolute; top: 50%; left: 50%;
          transform: translate(-50%, -50%); width: 200px; height: 200px;
        }
        .crosshair { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 60px; height: 60px; }
        .crosshair-h, .crosshair-v { position: absolute; top: 50%; left: 50%; }
        .crosshair-h { width: 25px; height: 2px; transform: translate(-50%, -50%); }
        .crosshair-v { width: 2px; height: 25px; transform: translate(-50%, -50%); }
        .target-ring {
          position: absolute; top: 50%; left: 50%; width: 80px; height: 80px;
          border: 2px solid; border-radius: 50%; animation: targetPulse 3s ease-in-out infinite;
        }
        .target-ring-outer {
          position: absolute; top: 50%; left: 50%; width: 280px; height: 280px;
          border: 2px solid; border-radius: 50%;
        }
        .target-dot {
          position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
          width: 4px; height: 4px; border-radius: 50%;
        }
        .focus-corners { position: absolute; top: 50%; left: 50%; width: 120px; height: 120px; }
        .corner { position: absolute; width: 20px; height: 20px; border: 2px solid var(--accent); box-shadow: 0 0 10px rgba(47,227,139,0.5); }
        .corner-tl { top: 0; left: 0; border-right: none; border-bottom: none; }
        .corner-tr { top: 0; right: 0; border-left: none; border-bottom: none; }
        .corner-bl { bottom: 0; left: 0; border-right: none; border-top: none; }
        .corner-br { bottom: 0; right: 0; border-left: none; border-top: none; }
        .scan-lines { position: absolute; inset: 0; overflow: hidden; }
        .scan-line {
          position: absolute; width: 100%; height: 2px;
          background: linear-gradient(90deg, transparent, var(--accent), transparent);
          opacity: 0.5; animation: scan 4s linear infinite;
        }
        .scan-line:nth-child(2) { animation-delay: 1.3s; }
        .scan-line:nth-child(3) { animation-delay: 2.6s; }
        @keyframes outerRingPulse { 0%,100% { transform: translate(-50%,-50%) scale(1); opacity: 0.3; } 50% { transform: translate(-50%,-50%) scale(1.1); opacity: 0.6; } }
        @keyframes targetPulse { 0%,100% { transform: translate(-50%,-50%) scale(1); opacity: 0.6; } 50% { transform: translate(-50%,-50%) scale(1.1); opacity: 0.85; } }
        @keyframes scan { 0% { top: -10px; opacity: 0; } 10%,90% { opacity: 0.5; } 100% { top: 100%; opacity: 0; } }
        @media (max-width: 768px) {
          .hud-panel { padding: 8px 10px; font-size: 0.62rem; min-width: 120px; }
          .hud-center { width: 150px; height: 150px; }
        }
      `}</style>
    </div>
  );
}

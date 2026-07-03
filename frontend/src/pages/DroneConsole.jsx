import React, { useState, useEffect, useMemo } from 'react';
import {
  Battery, Thermometer, Activity, Wifi, WifiOff, MapPinned, Radar, Route,
  Building2, DoorOpen, ShieldAlert, Rocket, LandPlot, Settings2, X,
  CheckCircle2, Clock, History, ChevronLeft, Plane, Gauge, SignalHigh,
  Crosshair, Layers, Bug, Maximize2, Mountain, Eye,
} from 'lucide-react';
import RoomReportPage from './RoomReportPage';
import MissionHistory from './MissionHistory';
import {
  DEMO_MODE, DEMO_STATS, DEMO_TAKEOFF_HEIGHT, DEMO_ROOM_TIMELINE,
  DEMO_CURRENT_ROOM_INDEX, DEMO_WALL_MEASUREMENTS, DEMO_ROOM_REPORTS,
} from '../demoConfig';
import './DroneConsole.css';

const API_URL = 'http://localhost:8002';

// Simulated feed tile (DEMO mode) — each feed kind gets its own visual signature.
function SimPane({ feed, compact = false }) {
  const Icon = feed.icon || Plane;
  return (
    <div className={`cs-sim cs-sim--${feed.kind} ${compact ? 'compact' : ''}`}>
      <div className="cs-sim-grid" />
      <div className="cs-sim-scan" />
      {!compact && <Icon size={42} className="cs-sim-icon" />}
      {compact && <Icon size={20} className="cs-sim-icon" />}
      {!compact && <div className="cs-sim-badge">{feed.label} · simulated</div>}
      {!compact && <div className="cs-sim-corners"><i /><i /><i /><i /></div>}
    </div>
  );
}

export default function DroneConsole({ onExit }) {
  const [connected, setConnected] = useState(false);
  const [stats, setStats] = useState({ battery: null, temperature: null, height: null, is_flying: false });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [autopilotStatus, setAutopilotStatus] = useState('Idle');
  const [wallMeasurements, setWallMeasurements] = useState({});
  const [scanMode, setScanMode] = useState('simple');
  const [startPosition, setStartPosition] = useState('hallway');
  const [targetFloor, setTargetFloor] = useState(null);
  const [stairSignals, setStairSignals] = useState({ sobel: true, gabor: true, da2: true });
  const [stairSingleFlight, setStairSingleFlight] = useState(false);
  const [roomCount, setRoomCount] = useState(3);
  const [roomReports, setRoomReports] = useState([]);
  const [roomTimeline, setRoomTimeline] = useState({});
  const [currentRoomIndex, setCurrentRoomIndex] = useState(null);
  const [reportsLoading, setReportsLoading] = useState(false);
  const [showDepthDebug, setShowDepthDebug] = useState(false);
  const [showStairDebug, setShowStairDebug] = useState(false);
  const [stairMetrics, setStairMetrics] = useState(null);
  const [selectedRoomIndex, setSelectedRoomIndex] = useState(null);
  const [showMissionModal, setShowMissionModal] = useState(false);
  const [showMissionHistory, setShowMissionHistory] = useState(false);

  const roomCountOptions = [1, 2, 3, 4, 5, 10];
  const scanModeApi = scanMode === 'simple' ? 'medium' : 'complex';

  const getStartPositionLabel = (v) =>
    v === 'hallway' ? 'Hallway' : v === 'stairwell' ? 'Stairwell' : v === 'stairs' ? 'Stairs' : v;
  const getRoomCountLabel = (v) => (Number(v) === 10 ? 'All open doors' : `${v} room${Number(v) > 1 ? 's' : ''}`);
  const normalizeAutopilotStatus = (s) => (!s || s === 'Inactiv' ? 'Idle' : s);

  useEffect(() => {
    if (!showMissionModal) return undefined;
    const onKeyDown = (e) => { if (e.key === 'Escape') setShowMissionModal(false); };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [showMissionModal]);

  // Live data (mock in DEMO mode, WebSocket otherwise).
  useEffect(() => {
    if (DEMO_MODE) {
      setConnected(true);
      setReportsLoading(false);
      setStats((p) => ({ ...p, ...DEMO_STATS }));
      setRoomReports(DEMO_ROOM_REPORTS);
      setRoomTimeline(DEMO_ROOM_TIMELINE);
      setCurrentRoomIndex(DEMO_CURRENT_ROOM_INDEX);
      return undefined;
    }

    let isMounted = true;
    let socket = null;
    let reconnectTimeout = null;
    const wsBase = API_URL.replace('http://', 'ws://').replace('https://', 'wss://');

    const connectSocket = () => {
      if (!isMounted) return;
      setReportsLoading(true);
      socket = new WebSocket(`${wsBase}/ws/live?room_count=${roomCount}`);
      socket.onopen = () => {
        if (!isMounted) return;
        setReportsLoading(false);
        try { socket.send(JSON.stringify({ type: 'set_room_count', room_count: roomCount })); } catch (e) { console.error(e); }
      };
      socket.onmessage = (event) => {
        if (!isMounted) return;
        try {
          const message = JSON.parse(event.data);
          if (message?.type !== 'live_update' || !message?.data) return;
          const payload = message.data;
          setConnected(Boolean(payload.connected));
          if (payload.stats) setStats((p) => ({ ...p, ...payload.stats }));
          if (payload.target) {
            setAutopilotStatus(normalizeAutopilotStatus(payload.target.autopilot_status));
            setWallMeasurements(payload.target.wall_measurements || {});
            if (payload.target.room_timeline && typeof payload.target.room_timeline === 'object') setRoomTimeline(payload.target.room_timeline);
            setCurrentRoomIndex(payload.target.current_room_index ?? null);
            setStairMetrics(payload.target.stair_metrics || null);
          }
          if (Array.isArray(payload.reports)) setRoomReports(payload.reports);
        } catch (e) { console.error(e); }
      };
      socket.onerror = () => { if (isMounted) setReportsLoading(true); };
      socket.onclose = () => { if (!isMounted) return; setReportsLoading(true); reconnectTimeout = setTimeout(connectSocket, 1200); };
    };
    connectSocket();
    return () => {
      isMounted = false;
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (socket && socket.readyState === WebSocket.OPEN) socket.close();
    };
  }, [roomCount]);

  useEffect(() => {
    setRoomTimeline((prev) => {
      const next = {};
      for (let index = 1; index <= roomCount; index += 1) {
        next[index] = prev?.[index] ?? prev?.[String(index)] ?? 'pending';
      }
      return next;
    });
  }, [roomCount]);

  const openReportPanel = (roomIndex) => setSelectedRoomIndex(roomIndex);
  const getRoomReport = (roomIndex) => roomReports.find((r) => Number(r.room_index) === Number(roomIndex)) || null;
  const selectedRoomReport = selectedRoomIndex ? getRoomReport(selectedRoomIndex) : null;

  const getRoomCheckpointState = (roomIndex) => {
    const state = roomTimeline?.[roomIndex] ?? roomTimeline?.[String(roomIndex)] ?? 'pending';
    return state === 'entered' || state === 'exited' ? state : 'pending';
  };

  const handleConnect = async () => {
    if (DEMO_MODE) { setConnected(true); setStats((p) => ({ ...p, ...DEMO_STATS })); return; }
    setLoading(true); setError(null);
    try {
      const response = await fetch(`${API_URL}/drone/connect`, { method: 'POST' });
      const data = await response.json();
      if (data.success) {
        setConnected(true);
        setStats({ battery: data.battery, temperature: data.temperature, height: 0, is_flying: false });
      } else setError(data.message || 'Connection failed');
    } catch (err) { setError('Cannot reach backend server. Make sure it is running.'); }
    finally { setLoading(false); }
  };

  const handleDisconnect = async () => {
    if (DEMO_MODE) { setConnected(false); setStats({ battery: null, temperature: null, height: null, is_flying: false }); return; }
    setLoading(true);
    try {
      await fetch(`${API_URL}/drone/disconnect`, { method: 'POST' });
      setConnected(false);
      setStats({ battery: null, temperature: null, height: null, is_flying: false });
    } catch (err) { console.error(err); } finally { setLoading(false); }
  };

  const handleTakeoff = async () => {
    if (DEMO_MODE) { setStats((p) => ({ ...p, is_flying: true, height: DEMO_TAKEOFF_HEIGHT })); return; }
    setLoading(true); setError(null);
    try {
      const response = await fetch(`${API_URL}/drone/takeoff?start_position=${startPosition}`, { method: 'POST' });
      const data = await response.json();
      if (!data.success) setError(data.message || 'Takeoff failed');
      else setStats((p) => ({ ...p, is_flying: true, height: typeof data.height === 'number' ? data.height : p.height }));
    } catch (err) { setError('Takeoff command failed'); } finally { setLoading(false); }
  };

  const handleLand = async () => {
    if (DEMO_MODE) { setStats((p) => ({ ...p, is_flying: false, height: 0 })); return; }
    setLoading(true); setError(null);
    try {
      const response = await fetch(`${API_URL}/drone/land`, { method: 'POST' });
      const data = await response.json();
      if (!data.success) setError(data.message || 'Landing failed');
      else setStats((p) => ({ ...p, is_flying: false, height: 0 }));
    } catch (err) { setError('Landing command failed'); } finally { setLoading(false); }
  };

  const handleEmergency = async () => {
    if (DEMO_MODE) { setStats((p) => ({ ...p, is_flying: false, height: 0 })); return; }
    try { await fetch(`${API_URL}/drone/emergency`, { method: 'POST' }); } catch (err) { console.error(err); }
  };

  const handleAutopilot = async () => {
    if (DEMO_MODE) { setAutopilotStatus('Exploring corridor'); setWallMeasurements(DEMO_WALL_MEASUREMENTS); return; }
    setLoading(true); setError(null);
    try {
      const signalsStr = Object.entries(stairSignals).filter(([, on]) => on).map(([k]) => k).join(',') || 'sobel,gabor,da2';
      const response = await fetch(`${API_URL}/drone/autopilot?scan_mode=${scanModeApi}&room_count=${roomCount}&start_position=${startPosition}&target_floor=${targetFloor ?? 1}&stair_signals=${signalsStr}&stair_single_flight=${stairSingleFlight}`, { method: 'POST' });
      const data = await response.json();
      if (!data.success) setError(data.detail || 'Failed to start autopilot');
    } catch (err) { setError('Communication error while starting autopilot'); } finally { setLoading(false); }
  };

  const getBatteryColor = (battery) => {
    if (battery === null) return 'var(--text-faint)';
    if (battery > 50) return 'var(--accent)';
    if (battery > 20) return 'var(--warn)';
    return 'var(--danger)';
  };

  const canStartAutopilot = stats.is_flying || (typeof stats.height === 'number' && stats.height > 20);
  const scannedCount = Object.values(roomTimeline).filter((s) => s === 'exited').length;

  // ── Viewport feeds ────────────────────────────────────────────────────
  // The live stream area is a dockable multi-pane viewport. Toggling a debug
  // view adds its feed(s); click any tile to promote it to the large pane.
  const feeds = useMemo(() => {
    const list = [{ id: 'live', label: 'Live stream', kind: 'live', endpoint: 'feed', icon: Eye }];
    if (showDepthDebug) {
      list.push({ id: 'depth', label: 'Depth map', kind: 'depth', endpoint: 'depth', icon: Layers });
    }
    if (showStairDebug) {
      list.push({ id: 'da2', label: 'Depth DA2', kind: 'da2', endpoint: 'stair_da2', icon: Mountain });
      list.push({ id: 'sobel', label: 'Sobel gradient', kind: 'sobel', endpoint: 'stair_sobel', icon: Layers });
      list.push({ id: 'gabor', label: 'Gabor filter', kind: 'gabor', endpoint: 'stair_gabor', icon: Radar });
    }
    return list;
  }, [showDepthDebug, showStairDebug]);

  const [primaryFeed, setPrimaryFeed] = useState('live');
  useEffect(() => {
    if (!feeds.some((f) => f.id === primaryFeed)) setPrimaryFeed('live');
  }, [feeds, primaryFeed]);

  const primary = feeds.find((f) => f.id === primaryFeed) || feeds[0];
  const others = feeds.filter((f) => f.id !== primary.id);

  const renderFeedBody = (feed, compact = false) => {
    if (!connected) {
      return (
        <div className={`cs-stream-empty ${compact ? 'sm' : ''}`}>
          <Plane size={compact ? 22 : 54} />
          {!compact && <p>Connect to the drone to view this feed.</p>}
        </div>
      );
    }
    if (DEMO_MODE) return <SimPane feed={feed} compact={compact} />;
    return <img src={`${API_URL}/video/${feed.endpoint}`} alt={feed.label} className="cs-video" />;
  };

  return (
    <div className="app-shell console">
      {/* ── Top bar ── */}
      <header className="cs-bar glass-strong">
        <div className="cs-bar-left">
          <button className="cs-back" onClick={onExit} title="Back to site">
            <ChevronLeft size={18} />
          </button>
          <div className="cs-brand">
            <span className="cs-brand-ico"><Plane size={18} /></span>
            <div>
              <h1>Drone Command Console</h1>
              <p>Live tactical corridor scanning</p>
            </div>
          </div>
        </div>
        <div className="cs-bar-right">
          <div className={`cs-conn ${connected ? 'on' : 'off'}`}>
            {connected ? <Wifi size={15} /> : <WifiOff size={15} />}
            <span>{connected ? 'Connected' : 'Disconnected'}</span>
          </div>
          {connected && (
            <button className="btn btn-ghost cs-disc" onClick={handleDisconnect} disabled={loading}>
              {loading ? 'Disconnecting…' : 'Disconnect'}
            </button>
          )}
        </div>
      </header>

      <div className="cs-main">
        {/* ── Left: stream + timeline ── */}
        <div className="cs-col-left">
          <section className="cs-stream glass">
            <div className="cs-stream-head">
              <span className="chip"><span className="dot" /> {primary.label}</span>
              <div className="cs-view-toggles">
                <button
                  className={`cs-vt ${showDepthDebug ? 'on' : ''}`}
                  onClick={() => setShowDepthDebug((p) => !p)}
                  disabled={!connected}
                  title="Toggle depth map pane"
                >
                  <Layers size={13} /> Depth
                </button>
                <button
                  className={`cs-vt ${showStairDebug ? 'on' : ''}`}
                  onClick={() => setShowStairDebug((p) => !p)}
                  disabled={!connected}
                  title="Toggle stair-climber sensor panes"
                >
                  <Mountain size={13} /> Stairs
                </button>
              </div>
            </div>

            <div className="cs-viewport">
              <div className="cs-vp-main">
                {renderFeedBody(primary)}
                <span className="cs-vp-tag">{primary.label}</span>
                {feeds.length > 1 && <span className="cs-vp-count">{feeds.length} feeds</span>}
              </div>

              {others.length > 0 && (
                <div className="cs-filmstrip" data-count={others.length}>
                  {others.map((f) => (
                    <button
                      key={f.id}
                      type="button"
                      className="cs-thumb"
                      onClick={() => setPrimaryFeed(f.id)}
                      title={`Focus ${f.label}`}
                    >
                      <div className="cs-thumb-body">{renderFeedBody(f, true)}</div>
                      <span className="cs-thumb-label">{f.label}<Maximize2 size={11} /></span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {showStairDebug && stairMetrics && (
              <div className="cs-metrics cs-metrics-inline">
                <h4>Stair climber metrics</h4>
                <div className="cs-metrics-grid">
                  {Object.entries(stairMetrics).map(([key, value]) => (
                    <div key={key} className="cs-metric">
                      <div className="cs-metric-k">{key}</div>
                      <div className="cs-metric-v">{typeof value === 'number' ? value.toFixed(3) : String(value)}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>

          <section className="cs-timeline glass">
            <div className="cs-tl-head">
              <div>
                <h3>Room scanning progress</h3>
                <p>{scannedCount}/{roomCount} rooms cleared</p>
              </div>
              {reportsLoading && <span className="cs-syncing"><span className="dot amber" /> Syncing…</span>}
            </div>

            <div className="cs-rooms">
              {Array.from({ length: roomCount }, (_, index) => {
                const roomIndex = index + 1;
                const report = getRoomReport(roomIndex);
                const isSelected = selectedRoomIndex === roomIndex;
                const checkpointState = getRoomCheckpointState(roomIndex);
                const isCurrentRoom = Number(currentRoomIndex) === Number(roomIndex);
                const isReportReady = Boolean(report?.room_label || report?.saved_report || report?.live?.pre_entry_ai_analysis);

                return (
                  <div key={roomIndex} className="cs-room-wrap">
                    <button
                      type="button"
                      className={`cs-room checkpoint-${checkpointState} ${isCurrentRoom ? 'current' : ''} ${isSelected ? 'selected' : ''}`}
                      onClick={() => openReportPanel(roomIndex)}
                    >
                      <div className="cs-room-top">
                        <span className="cs-room-idx">{String(roomIndex).padStart(2, '0')}</span>
                        <span className={`cs-room-pill ${checkpointState}`}>
                          {checkpointState === 'exited' ? 'Cleared' : checkpointState === 'entered' ? 'Inside' : 'Pending'}
                        </span>
                      </div>
                      <div className="cs-room-label">
                        {isReportReady && report?.room_label ? (
                          <><CheckCircle2 size={14} /> {report.room_label}</>
                        ) : (
                          <><Clock size={14} /> {isCurrentRoom ? 'Scanning…' : 'Not scanned'}</>
                        )}
                      </div>
                      {isCurrentRoom && <div className="cs-room-scanbar" />}
                    </button>
                    {roomIndex < roomCount && <div className={`cs-room-link ${checkpointState === 'exited' ? 'done' : ''}`} />}
                  </div>
                );
              })}
            </div>
          </section>
        </div>

        {/* ── Right: controls ── */}
        <aside className="cs-col-right">
          <div className="cs-panel glass">
            <h2 className="cs-panel-title">Control center</h2>

            {error && <div className="cs-error">{error}</div>}

            {/* Mission profile */}
            <div className="cs-block">
              <div className="cs-block-head">
                <span className="cs-block-title"><Route size={15} /> Mission profile</span>
              </div>
              <div className="cs-profile-actions">
                <button className="btn btn-ghost cs-sm" onClick={() => setShowMissionModal(true)} disabled={loading}>
                  <Settings2 size={14} /> Configure
                </button>
                <button className="btn btn-ghost cs-sm" onClick={() => setShowMissionHistory(true)}>
                  <History size={14} /> History
                </button>
              </div>
              <div className="cs-chips">
                <span className="chip"><Radar size={13} /> {scanMode === 'simple' ? 'Simple scan' : 'Complex scan'}</span>
                <span className="chip"><DoorOpen size={13} /> {getRoomCountLabel(roomCount)}</span>
                <span className="chip"><MapPinned size={13} /> {getStartPositionLabel(startPosition)}</span>
                {startPosition === 'stairs' && <span className="chip"><Route size={13} /> Floor {targetFloor}</span>}
              </div>
            </div>

            {!connected && (
              <button className="btn btn-accent cs-wide" onClick={handleConnect} disabled={loading}>
                {loading ? 'Connecting…' : 'Connect drone'}
              </button>
            )}

            {connected && (
              <>
                {/* Telemetry */}
                <div className="cs-block">
                  <div className="cs-block-head"><span className="cs-block-title"><Gauge size={15} /> Telemetry</span></div>
                  <div className="cs-telemetry">
                    <div className="cs-tm">
                      <Battery size={16} style={{ color: getBatteryColor(stats.battery) }} />
                      <div><span>Battery</span><b>{stats.battery !== null ? `${stats.battery}%` : '--'}</b></div>
                    </div>
                    <div className="cs-tm">
                      <Thermometer size={16} />
                      <div><span>Temp</span><b>{stats.temperature !== null ? `${stats.temperature}°C` : '--'}</b></div>
                    </div>
                    <div className="cs-tm">
                      <Activity size={16} />
                      <div><span>Height</span><b>{stats.height !== null ? `${stats.height}cm` : '--'}</b></div>
                    </div>
                    <div className="cs-tm">
                      <SignalHigh size={16} />
                      <div><span>State</span><b>{stats.is_flying ? 'In flight' : 'On ground'}</b></div>
                    </div>
                  </div>
                </div>

                {/* Flight controls */}
                <div className="cs-block">
                  <div className="cs-block-head"><span className="cs-block-title"><Crosshair size={15} /> Flight controls</span></div>
                  <div className="cs-flight">
                    <button className="btn btn-accent cs-sm" onClick={handleTakeoff} disabled={loading || stats.is_flying}>
                      <Rocket size={14} /> Takeoff
                    </button>
                    <button className="btn btn-warn cs-sm" onClick={handleLand} disabled={loading || !stats.is_flying}>
                      <LandPlot size={14} /> Land
                    </button>
                    <button className="btn btn-danger cs-sm cs-emergency" onClick={handleEmergency}>
                      <ShieldAlert size={14} /> Emergency stop
                    </button>
                  </div>
                </div>

                {/* Autopilot */}
                <div className="cs-block cs-block-last">
                  <button className="btn cs-autopilot cs-wide" onClick={handleAutopilot} disabled={loading || !canStartAutopilot}>
                    <Route size={15} /> Start autopilot
                  </button>
                  <div className={`cs-ap-status ${autopilotStatus !== 'Idle' ? 'active' : ''}`}>
                    <div className="cs-ap-top">
                      <span>Autopilot status</span>
                      <span className={`cs-ap-state ${autopilotStatus !== 'Idle' ? 'live' : ''}`}>
                        {autopilotStatus !== 'Idle' && <span className="dot" />}{autopilotStatus}
                      </span>
                    </div>
                    {Object.keys(wallMeasurements).length > 0 && (
                      <div className="cs-walls">
                        <div className="cs-walls-title">Depth measurements</div>
                        <div className="cs-walls-grid">
                          {wallMeasurements.front != null && <div><span>Front</span><b>{wallMeasurements.front.toFixed(2)}m</b></div>}
                          {wallMeasurements.left != null && <div><span>Left</span><b>{wallMeasurements.left.toFixed(2)}m</b></div>}
                          {wallMeasurements.right != null && <div><span>Right</span><b>{wallMeasurements.right.toFixed(2)}m</b></div>}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
        </aside>
      </div>

      {/* ── Room report modal ── */}
      {selectedRoomIndex && (
        <div className="cs-overlay" onClick={() => setSelectedRoomIndex(null)}>
          <div className="cs-modal glass-strong cs-modal-report" onClick={(e) => e.stopPropagation()}>
            <div className="cs-modal-head">
              <h3>Room scan report</h3>
              <button className="cs-close" onClick={() => setSelectedRoomIndex(null)}><X size={18} /></button>
            </div>
            <div className="cs-modal-body">
              <RoomReportPage roomIndex={selectedRoomIndex} embedded reportDataOverride={selectedRoomReport} />
            </div>
          </div>
        </div>
      )}

      {/* ── Mission config modal ── */}
      {showMissionModal && (
        <div className="cs-overlay" onClick={() => setShowMissionModal(false)}>
          <div className="cs-modal glass-strong" onClick={(e) => e.stopPropagation()}>
            <div className="cs-modal-head">
              <div>
                <h3>Mission configuration</h3>
                <p className="cs-modal-sub">Tune how the drone starts and explores the corridor.</p>
              </div>
              <button className="cs-close" onClick={() => setShowMissionModal(false)}><X size={18} /></button>
            </div>
            <div className="cs-modal-body">
              <div className="cs-form-block">
                <label>Scan mode</label>
                <div className="cs-choice-grid">
                  <button className={`cs-choice ${scanMode === 'simple' ? 'active' : ''}`} onClick={() => setScanMode('simple')}>
                    <Radar size={18} /><span>Simple scan</span><small>Balanced sweep and 360° room coverage</small>
                  </button>
                  <button className={`cs-choice ${scanMode === 'complex' ? 'active' : ''}`} onClick={() => setScanMode('complex')}>
                    <Route size={18} /><span>Complex scan</span><small>Extended path with deeper wall measurements</small>
                  </button>
                </div>
              </div>

              <div className="cs-form-block">
                <label htmlFor="room-count">Rooms to scan</label>
                <select id="room-count" value={roomCount} onChange={(e) => setRoomCount(Number(e.target.value))} className="cs-select">
                  {roomCountOptions.map((value) => (
                    <option key={value} value={value}>{value === 10 ? 'All open doors (auto)' : `${value} room${value > 1 ? 's' : ''}`}</option>
                  ))}
                </select>
              </div>

              <div className="cs-form-block">
                <label>Starting point</label>
                <div className="cs-choice-grid three">
                  <button className={`cs-choice sm ${startPosition === 'hallway' ? 'active' : ''}`} onClick={() => setStartPosition('hallway')}>
                    <Building2 size={18} /><span>Hallway</span>
                  </button>
                  <button className={`cs-choice sm ${startPosition === 'stairwell' ? 'active' : ''}`} onClick={() => setStartPosition('stairwell')}>
                    <MapPinned size={18} /><span>Stairwell</span>
                  </button>
                  <button className={`cs-choice sm ${startPosition === 'stairs' ? 'active' : ''}`} onClick={() => { setStartPosition('stairs'); setTargetFloor(1); }}>
                    <Route size={18} /><span>Stairs</span>
                  </button>
                </div>
              </div>

              {startPosition === 'stairs' && (
                <div className="cs-form-block">
                  <label htmlFor="target-floor">Target floor</label>
                  <select id="target-floor" value={targetFloor === null ? 1 : targetFloor} onChange={(e) => setTargetFloor(Number(e.target.value))} className="cs-select">
                    <option value={1}>Floor 1</option>
                    <option value={2}>Floor 2</option>
                    <option value={3}>Floor 3</option>
                  </select>

                  <label style={{ marginTop: 12 }}>Detection signals</label>
                  <div className="cs-signal-grid">
                    {[
                      { key: 'sobel', label: 'Sobel', hint: 'muchii orizontale trepte' },
                      { key: 'gabor', label: 'Gabor', hint: 'pattern periodic' },
                      { key: 'da2', label: 'DA2', hint: 'adâncime (depth)' },
                    ].map((sig) => {
                      const on = stairSignals[sig.key];
                      const onlyOneLeft = Object.values(stairSignals).filter(Boolean).length === 1;
                      return (
                        <button
                          key={sig.key}
                          type="button"
                          className={`cs-signal-chip ${on ? 'on' : ''}`}
                          title={sig.hint}
                          onClick={() => {
                            if (on && onlyOneLeft) return; // nu lăsa zero semnale active
                            setStairSignals((p) => ({ ...p, [sig.key]: !p[sig.key] }));
                          }}
                        >
                          <span className="cs-signal-box">{on ? '✓' : ''}</span>
                          <span>{sig.label}</span>
                        </button>
                      );
                    })}
                  </div>

                  <button
                    type="button"
                    className={`cs-signal-chip ${stairSingleFlight ? 'on' : ''}`}
                    style={{ marginTop: 12, width: '100%' }}
                    title="Urcă o singură serie de scări până la palier și aterizează acolo (fără rotații / al doilea zbor). Ideal pentru teste rapide."
                    onClick={() => setStairSingleFlight((v) => !v)}
                  >
                    <span className="cs-signal-box">{stairSingleFlight ? '✓' : ''}</span>
                    <span>Single flight (test rapid — un zbor + aterizare pe palier)</span>
                  </button>
                </div>
              )}
            </div>
            <div className="cs-modal-foot">
              <button className="btn btn-accent" onClick={() => setShowMissionModal(false)}>Done</button>
            </div>
          </div>
        </div>
      )}

      {showMissionHistory && <MissionHistory onClose={() => setShowMissionHistory(false)} />}
    </div>
  );
}

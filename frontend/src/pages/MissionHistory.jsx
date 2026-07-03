import React, { useState, useEffect, useCallback } from 'react';
import {
    X,
    ChevronDown,
    ChevronRight,
    Calendar,
    Clock,
    CheckCircle2,
    AlertTriangle,
    User,
    Video,
    Building2,
    Flame,
    Shield,
    Activity,
    Crosshair,
    Ruler,
    ScanLine,
    Timer,
    Cpu,
    Gauge,
    DoorOpen,
    ArrowLeftRight,
} from 'lucide-react';
import { DEMO_MODE, DEMO_MISSIONS, DEMO_MISSION_DETAILS } from '../demoConfig';
import './MissionHistory.css';

const API_URL = 'http://localhost:8002';

function formatDuration(startedAt, endedAt) {
    if (!startedAt || !endedAt) return '—';
    const diff = Math.round((new Date(endedAt) - new Date(startedAt)) / 1000);
    if (diff < 60) return `${diff}s`;
    const m = Math.floor(diff / 60);
    const s = diff % 60;
    return `${m}m ${s}s`;
}

function formatDate(isoStr) {
    if (!isoStr) return '—';
    const d = new Date(isoStr);
    return d.toLocaleString('ro-RO', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    });
}

function StatusBadge({ status }) {
    const map = {
        completed: { label: 'Completed', cls: 'badge-completed' },
        in_progress: { label: 'In Progress', cls: 'badge-in-progress' },
        aborted: { label: 'Aborted', cls: 'badge-aborted' },
    };
    const { label, cls } = map[status] || { label: status, cls: '' };
    return <span className={`mh-badge ${cls}`}>{label}</span>;
}

function HazardTag({ fire, smoke }) {
    if (!fire && !smoke) return <span className="mh-safe-tag"><Shield size={12} /> Safe</span>;
    return (
        <span className="mh-hazard-tag">
            <Flame size={12} />
            {fire && smoke ? 'Fire & Smoke' : fire ? 'Fire' : 'Smoke'}
        </span>
    );
}

function PersonCard({ person, apiUrl }) {
    const imgUrl = person.image_path
        ? (person.image_path.startsWith('http') ? person.image_path : `${apiUrl}${person.image_path}`)
        : null;

    const medicalColor = {
        STABLE: '#3ee89c',
        CRITICAL: '#ff4444',
        UNKNOWN: '#bbb',
    }[person.medical_state] || '#bbb';

    return (
        <div className="mh-person-card">
            {imgUrl && (
                <img src={imgUrl} alt={`Track ${person.track_id}`} className="mh-person-img" />
            )}
            <div className="mh-person-info">
                <div className="mh-person-row">
                    <User size={12} />
                    <span>Track #{person.track_id}</span>
                    {person.posture && <span className="mh-posture-tag">{person.posture}</span>}
                </div>
                {person.medical_state && (
                    <div className="mh-person-row" style={{ color: medicalColor }}>
                        <Activity size={12} />
                        <span>{person.medical_state}</span>
                    </div>
                )}
                {person.medical_description && (
                    <p className="mh-person-desc">{person.medical_description}</p>
                )}
            </div>
        </div>
    );
}

function RoomScanCard({ scan, apiUrl }) {
    const [expanded, setExpanded] = useState(false);

    const preEntryImg = scan.pre_entry_image_path
        ? (scan.pre_entry_image_path.startsWith('http')
            ? scan.pre_entry_image_path
            : `${apiUrl}${scan.pre_entry_image_path}`)
        : null;

    const ocrImg = scan.ocr_crop_path
        ? (scan.ocr_crop_path.startsWith('http') ? scan.ocr_crop_path : `${apiUrl}${scan.ocr_crop_path}`)
        : null;

    const levelColor = {
        SAFE: '#3ee89c',
        WARNING: '#ffa500',
        DANGER: '#ff4444',
        unknown: '#bbb',
    }[scan.pre_entry_level] || '#bbb';

    return (
        <div className="mh-room-card">
            <button
                type="button"
                className="mh-room-header"
                onClick={() => setExpanded((v) => !v)}
            >
                <div className="mh-room-title">
                    <Building2 size={14} />
                    <span>Room {scan.room_index}</span>
                    {scan.room_label && (
                        <span className="mh-room-label-tag">{scan.room_label}</span>
                    )}
                </div>
                <div className="mh-room-meta">
                    <HazardTag fire={scan.hazard_fire} smoke={scan.hazard_smoke} />
                    {scan.persons_detected > 0 && (
                        <span className="mh-persons-count">
                            <User size={12} /> {scan.persons_detected}
                        </span>
                    )}
                    {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </div>
            </button>

            {expanded && (
                <div className="mh-room-body">
                    <div className="mh-room-stats">
                        <div className="mh-stat">
                            <span className="mh-stat-label">Frames analyzed</span>
                            <span className="mh-stat-value">{scan.frames_analyzed ?? '—'}</span>
                        </div>
                        <div className="mh-stat">
                            <span className="mh-stat-label">Scan duration</span>
                            <span className="mh-stat-value">{formatDuration(scan.scan_start, scan.scan_end)}</span>
                        </div>
                        {scan.pre_entry_level && (
                            <div className="mh-stat">
                                <span className="mh-stat-label">Pre-entry AI</span>
                                <span className="mh-stat-value" style={{ color: levelColor }}>
                                    {scan.pre_entry_level}
                                </span>
                            </div>
                        )}
                    </div>

                    {scan.pre_entry_description && (
                        <p className="mh-pre-entry-desc">{scan.pre_entry_description}</p>
                    )}

                    <div className="mh-images-row">
                        {preEntryImg && (
                            <div className="mh-img-box">
                                <p className="mh-img-label">Pre-entry AI frame</p>
                                <img src={preEntryImg} alt="Pre-entry" className="mh-thumb" />
                            </div>
                        )}
                        {ocrImg && (
                            <div className="mh-img-box">
                                <p className="mh-img-label">OCR frame</p>
                                <img src={ocrImg} alt="OCR" className="mh-thumb" />
                            </div>
                        )}
                    </div>

                    {scan.persons && scan.persons.length > 0 && (
                        <div className="mh-persons-section">
                            <h4>Persons detected</h4>
                            <div className="mh-persons-grid">
                                {scan.persons.map((p) => (
                                    <PersonCard key={p.id} person={p} apiUrl={apiUrl} />
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

function VideoSection({ videos, apiUrl }) {
    if (!videos || videos.length === 0) return null;

    const typeLabels = {
        hallway_raw: 'Hallway (raw AI)',
        hallway_da2: 'Hallway (DA2 depth)',
        stairwell_raw: 'Stairwell (raw)',
        stairwell_da2: 'Stairwell (DA2)',
        stair_climber_raw: 'Stair Climber (raw)',
        stair_climber_grid: 'Stair Climber (grid)',
    };

    return (
        <div className="mh-videos-section">
            <h4><Video size={14} /> Recordings</h4>
            <div className="mh-videos-grid">
                {videos.map((v) => (
                    <div key={v.id} className="mh-video-card">
                        <p className="mh-video-type">{typeLabels[v.video_type] || v.video_type}</p>
                        {v.url ? (
                            <video
                                src={`${apiUrl}${v.url}`}
                                controls
                                className="mh-video-player"
                                preload="metadata"
                            />
                        ) : (
                            <p className="mh-video-missing">File not accessible</p>
                        )}
                    </div>
                ))}
            </div>
        </div>
    );
}

function formatSecs(s) {
    if (s == null || Number.isNaN(s)) return '—';
    if (s < 10) return `${s.toFixed(1)}s`;
    const m = Math.floor(s / 60);
    const sec = Math.round(s % 60);
    return m > 0 ? `${m}m ${sec}s` : `${Math.round(s)}s`;
}

const MODULE_ICONS = {
    centering: Crosshair,
    distance_hold: Ruler,
    scan: ScanLine,
    door_search: DoorOpen,
    door_entry: DoorOpen,
    lateral_align: ArrowLeftRight,
    ocr_scan: Cpu,
    transition: ArrowLeftRight,
    stairwell: Activity,
    other: Activity,
};

function describeCommand(cmd) {
    if (cmd.kind === 'rotation') {
        return `Rotate ${cmd.clockwise === false ? 'left' : 'right'} ${Math.round(cmd.degrees)}°`;
    }
    const parts = [];
    const lr = cmd.lr || 0;
    const fb = cmd.fb || 0;
    const yaw = cmd.yaw || 0;
    if (cmd.kind === 'translation') {
        if (fb) parts.push(`${fb > 0 ? 'forward' : 'back'} ${Math.abs(Math.round(fb))}cm`);
        if (lr) parts.push(`${lr > 0 ? 'right' : 'left'} ${Math.abs(Math.round(lr))}cm`);
        return parts.join(' · ') || 'move';
    }
    // rc command (speeds)
    if (fb) parts.push(`${fb > 0 ? 'forward' : 'back'} ${Math.abs(fb)}`);
    if (lr) parts.push(`${lr > 0 ? 'right' : 'left'} ${Math.abs(lr)}`);
    if (yaw) parts.push(`${yaw > 0 ? 'rotate ↻' : 'rotate ↺'} ${Math.abs(yaw)}`);
    if (parts.length === 0) parts.push('hold');
    return parts.join(' · ');
}

function EmaSparkline({ samples }) {
    const ema = (samples || []).filter((s) => s.key === 'ratio_ema').map((s) => s.value);
    if (ema.length < 2) return null;
    const w = 120;
    const h = 28;
    const min = Math.min(...ema);
    const max = Math.max(...ema);
    const range = max - min || 1;
    const pts = ema
        .map((v, i) => {
            const x = (i / (ema.length - 1)) * (w - 4) + 2;
            const y = h - 2 - ((v - min) / range) * (h - 4);
            return `${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(' ');
    return (
        <svg className="mh-spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
            <polyline points={pts} fill="none" stroke="var(--accent)" strokeWidth="1.6" />
        </svg>
    );
}

function ModuleCard({ module }) {
    const [open, setOpen] = useState(false);
    const Icon = MODULE_ICONS[module.module_key] || Activity;
    const hasEma = module.ema_variation != null;
    const cmdCount = module.command_count ?? (module.commands ? module.commands.length : 0);

    return (
        <div className="mh-module-card">
            <button type="button" className="mh-module-header" onClick={() => setOpen((v) => !v)}>
                <div className="mh-module-title">
                    <Icon size={14} className="mh-module-icon" />
                    <span>{module.module_label}</span>
                </div>
                <div className="mh-module-meta">
                    <span className="mh-module-stat"><Timer size={11} /> {formatSecs(module.duration_s)}</span>
                    <span className="mh-module-stat"><Gauge size={11} /> {cmdCount} cmd</span>
                    {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                </div>
            </button>

            {open && (
                <div className="mh-module-body">
                    <div className="mh-module-metrics">
                        <div className="mh-metric">
                            <span className="mh-metric-label">Duration</span>
                            <span className="mh-metric-value">{formatSecs(module.duration_s)}</span>
                        </div>
                        <div className="mh-metric">
                            <span className="mh-metric-label">Commands</span>
                            <span className="mh-metric-value">{cmdCount}</span>
                        </div>
                        <div className="mh-metric">
                            <span className="mh-metric-label">Command time</span>
                            <span className="mh-metric-value">{formatSecs(module.total_command_time_s)}</span>
                        </div>
                        {hasEma && (
                            <div className="mh-metric">
                                <span className="mh-metric-label">EMA variation</span>
                                <span className="mh-metric-value">±{module.ema_variation}</span>
                            </div>
                        )}
                    </div>

                    {hasEma && (
                        <div className="mh-ema-row">
                            <div className="mh-ema-stats">
                                <span>min <b>{module.ema_min}</b></span>
                                <span>max <b>{module.ema_max}</b></span>
                                <span>final <b>{module.ema_final}</b></span>
                            </div>
                            <EmaSparkline samples={module.samples} />
                        </div>
                    )}

                    {module.commands && module.commands.length > 0 && (
                        <div className="mh-cmd-list">
                            {module.commands.map((cmd) => (
                                <div key={cmd.seq} className="mh-cmd-row">
                                    <span className="mh-cmd-seq">#{cmd.seq}</span>
                                    <span className="mh-cmd-desc">{describeCommand(cmd)}</span>
                                    {cmd.kind !== 'rotation' && cmd.duration_s > 0 && (
                                        <span className="mh-cmd-dur">{cmd.duration_s.toFixed(2)}s</span>
                                    )}
                                    {cmd.label && <span className="mh-cmd-label">{cmd.label}</span>}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

function ModuleTelemetrySection({ modules }) {
    if (!modules || modules.length === 0) return null;

    // Group modules per room, preserving order (seq).
    const byRoom = new Map();
    modules.forEach((m) => {
        const key = m.room_index == null ? 'general' : m.room_index;
        if (!byRoom.has(key)) byRoom.set(key, []);
        byRoom.get(key).push(m);
    });

    const totalCmds = modules.reduce((acc, m) => acc + (m.command_count ?? (m.commands ? m.commands.length : 0)), 0);

    return (
        <div className="mh-telemetry-section">
            <h4><Activity size={14} /> Module telemetry ({totalCmds} commands)</h4>
            {Array.from(byRoom.entries()).map(([room, mods]) => (
                <div key={room} className="mh-telemetry-room">
                    <p className="mh-telemetry-room-title">
                        {room === 'general' ? 'General' : `Room ${room}`}
                    </p>
                    {mods.map((m) => (
                        <ModuleCard key={m.id || m.seq} module={m} />
                    ))}
                </div>
            ))}
        </div>
    );
}

function StairMultiSparkline({ samples, signals }) {
    if (!samples || samples.length < 2) return null;
    const w = 240, h = 60;
    const active = new Set(String(signals || '').split(',').map((s) => s.trim()).filter(Boolean));
    // afișăm doar semnalele active (fără placeholder-e), plus conf-urile finale punctate
    const signalSeries = [
        { key: 'grad_score', color: '#b4b400', label: 'Sobel', sig: 'sobel' },
        { key: 'gabor_score', color: '#b450c8', label: 'Gabor', sig: 'gabor' },
        { key: 'depth_stair', color: '#22c0ff', label: 'DA2', sig: 'da2' },
    ].filter((s) => active.size === 0 || active.has(s.sig));
    const confSeries = [
        { key: 'stair_conf', color: 'var(--accent)', label: 'Conf', dash: '3,2' },
    ];
    const series = [...signalSeries, ...confSeries];
    const line = (key) => samples
        .map((s, i) => {
            const x = (i / (samples.length - 1)) * (w - 4) + 2;
            const v = Math.max(0, Math.min(1, Number(s[key]) || 0));
            const y = h - 2 - v * (h - 4);
            return `${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(' ');
    return (
        <div>
            <svg className="mh-spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
                {series.map((s) => (
                    <polyline key={s.key} points={line(s.key)} fill="none" stroke={s.color} strokeWidth="1.4" strokeDasharray={s.dash || undefined} />
                ))}
            </svg>
            <div className="mh-stair-legend">
                {series.map((s) => (
                    <span key={s.key}><i style={{ background: s.color }} />{s.label}</span>
                ))}
            </div>
        </div>
    );
}

function StairFlightCard({ flight, signals }) {
    const [open, setOpen] = useState(false);
    return (
        <div className="mh-module-card">
            <button type="button" className="mh-module-header" onClick={() => setOpen((v) => !v)}>
                <span>Flight {Number(flight.flight_index) + 1}</span>
                <span className="mh-module-dur">{formatSecs(flight.total_duration_s)} · {flight.outcome}</span>
            </button>
            {open && (
                <div className="mh-module-body">
                    <div className="mh-metric-row">
                        <div><span className="mh-metric-label">Search</span><span className="mh-metric-value">{formatSecs(flight.search_duration_s)}</span></div>
                        <div><span className="mh-metric-label">Climbing</span><span className="mh-metric-value">{formatSecs(flight.climbing_duration_s)}</span></div>
                        <div><span className="mh-metric-label">Pre-land</span><span className="mh-metric-value">{formatSecs(flight.preland_duration_s)}</span></div>
                        <div><span className="mh-metric-label">Samples</span><span className="mh-metric-value">{flight.sample_count ?? (flight.samples ? flight.samples.length : 0)}</span></div>
                    </div>
                    <StairMultiSparkline samples={flight.samples} signals={signals} />
                    {flight.id && (flight.sample_count || (flight.samples && flight.samples.length)) ? (
                        <a
                            className="mh-chart-dl"
                            href={`${API_URL}/stair_chart/${flight.id}.png`}
                            target="_blank"
                            rel="noreferrer"
                        >
                            ⬇ Salvează graficul (PNG)
                        </a>
                    ) : null}
                </div>
            )}
        </div>
    );
}

function StairTelemetrySection({ climbs }) {
    if (!climbs || climbs.length === 0) return null;
    return (
        <div className="mh-telemetry-section">
            <h4><Activity size={14} /> Stair climb telemetry</h4>
            {climbs.map((c) => (
                <div key={c.id} className="mh-telemetry-room">
                    <p className="mh-telemetry-room-title">
                        Floor {c.target_floor} · signals: {c.signals} · {c.success ? '✅ success' : '⚠️ incomplete'}
                        {c.duration_s != null ? ` · ${formatSecs(c.duration_s)}` : ''}
                        {c.battery_start != null ? ` · bat ${c.battery_start}→${c.battery_end ?? '?'}%` : ''}
                    </p>
                    {(c.flights || []).map((f) => (
                        <StairFlightCard key={f.id || f.flight_index} flight={f} signals={c.signals} />
                    ))}
                </div>
            ))}
        </div>
    );
}

function MissionDetail({ missionId, onClose }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        if (DEMO_MODE) {
            setData(DEMO_MISSION_DETAILS[missionId] || null);
            setError(DEMO_MISSION_DETAILS[missionId] ? null : 'Could not load mission.');
            setLoading(false);
            return undefined;
        }

        let mounted = true;
        fetch(`${API_URL}/missions/${missionId}`)
            .then((r) => r.json())
            .then((d) => {
                if (!mounted) return;
                if (d.success) {
                    setData(d);
                } else {
                    setError('Could not load mission.');
                }
            })
            .catch(() => {
                if (mounted) setError('Network error.');
            })
            .finally(() => {
                if (mounted) setLoading(false);
            });
        return () => { mounted = false; };
    }, [missionId]);

    return (
        <div className="mh-detail-overlay" onClick={onClose}>
            <div className="mh-detail-modal" onClick={(e) => e.stopPropagation()}>
                <div className="mh-detail-header">
                    <div>
                        <h3>Mission Detail</h3>
                        {data?.mission && (
                            <p className="mh-detail-subtitle">
                                {formatDate(data.mission.started_at)}
                                {' · '}
                                {formatDuration(data.mission.started_at, data.mission.ended_at)}
                            </p>
                        )}
                    </div>
                    <button type="button" className="mh-close-btn" onClick={onClose}>
                        <X size={18} />
                    </button>
                </div>

                <div className="mh-detail-body">
                    {loading && <p className="mh-loading">Loading...</p>}
                    {error && <p className="mh-error">{error}</p>}

                    {data && (
                        <>
                            <div className="mh-mission-meta-chips">
                                <span className="mh-chip">{data.mission.scan_mode}</span>
                                <span className="mh-chip">{data.mission.start_position}</span>
                                <span className="mh-chip">{data.mission.room_count} room{data.mission.room_count !== 1 ? 's' : ''}</span>
                                <StatusBadge status={data.mission.status} />
                            </div>

                            <div className="mh-room-scans">
                                {data.room_scans && data.room_scans.length > 0 ? (
                                    data.room_scans.map((scan) => (
                                        <RoomScanCard key={scan.id} scan={scan} apiUrl={API_URL} />
                                    ))
                                ) : (
                                    <p className="mh-empty">No room scans recorded for this mission.</p>
                                )}
                            </div>

                            <ModuleTelemetrySection modules={data.modules} />

                            <StairTelemetrySection climbs={data.stair_climbs} />

                            <VideoSection videos={data.videos} apiUrl={API_URL} />
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}

export default function MissionHistory({ onClose }) {
    const [missions, setMissions] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [selectedId, setSelectedId] = useState(null);

    const fetchMissions = useCallback(() => {
        setLoading(true);
        if (DEMO_MODE) {
            setMissions(DEMO_MISSIONS);
            setTotal(DEMO_MISSIONS.length);
            setError(null);
            setLoading(false);
            return;
        }
        fetch(`${API_URL}/missions?limit=50`)
            .then((r) => r.json())
            .then((d) => {
                if (d.success) {
                    setMissions(d.missions);
                    setTotal(d.total);
                    setError(null);
                } else {
                    setError('Could not load missions.');
                }
            })
            .catch(() => setError('Cannot reach backend server.'))
            .finally(() => setLoading(false));
    }, []);

    useEffect(() => {
        fetchMissions();
    }, [fetchMissions]);

    useEffect(() => {
        const onKey = (e) => {
            if (e.key === 'Escape') {
                if (selectedId) {
                    setSelectedId(null);
                } else {
                    onClose();
                }
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [onClose, selectedId]);

    return (
        <div className="mh-overlay" onClick={onClose}>
            <div className="mh-panel" onClick={(e) => e.stopPropagation()}>
                <div className="mh-panel-header">
                    <div>
                        <h2>Mission History</h2>
                        {!loading && <p className="mh-total">{total} mission{total !== 1 ? 's' : ''} recorded</p>}
                    </div>
                    <button type="button" className="mh-close-btn" onClick={onClose}>
                        <X size={20} />
                    </button>
                </div>

                <div className="mh-panel-body">
                    {loading && <p className="mh-loading">Loading missions...</p>}
                    {error && <p className="mh-error">{error}</p>}

                    {!loading && !error && missions.length === 0 && (
                        <div className="mh-empty-state">
                            <Building2 size={40} className="mh-empty-icon" />
                            <p>No missions recorded yet.</p>
                            <p className="mh-empty-sub">Missions are saved automatically when autopilot runs.</p>
                        </div>
                    )}

                    {missions.map((m) => (
                        <button
                            key={m.id}
                            type="button"
                            className="mh-mission-row"
                            onClick={() => setSelectedId(m.id)}
                        >
                            <div className="mh-mission-left">
                                <div className="mh-mission-date">
                                    <Calendar size={13} />
                                    <span>{formatDate(m.started_at)}</span>
                                </div>
                                <div className="mh-mission-chips">
                                    <span className="mh-chip-sm">{m.scan_mode}</span>
                                    <span className="mh-chip-sm">{m.start_position}</span>
                                    <span className="mh-chip-sm">{m.room_count} room{m.room_count !== 1 ? 's' : ''}</span>
                                </div>
                            </div>
                            <div className="mh-mission-right">
                                <div className="mh-mission-dur">
                                    <Clock size={12} />
                                    <span>{formatDuration(m.started_at, m.ended_at)}</span>
                                </div>
                                <StatusBadge status={m.status} />
                                <ChevronRight size={14} className="mh-chevron" />
                            </div>
                        </button>
                    ))}
                </div>
            </div>

            {selectedId && (
                <MissionDetail
                    missionId={selectedId}
                    onClose={() => setSelectedId(null)}
                />
            )}
        </div>
    );
}

import React, { useState, useEffect, useRef } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera } from '@react-three/drei';
import {
  ScanSearch, RadioTower, Crosshair, Zap, ShieldCheck, BrainCircuit,
  Gauge, Activity, BatteryMedium, ArrowUpRight,
  Plug, PlugZap, Rocket, Cpu, Satellite,
  Fan, Cylinder, Box, Camera, Shield, Tag, GripVertical, ChevronDown,
} from 'lucide-react';

import { DroneModel, ParticleField, LightingSetup } from '../components/DroneScene';
import HUD from '../components/HUD';
import { Reveal, Counter, ScrollProgress, Navbar } from '../components/ui';
import { useScrollAnimation } from '../hooks/useScrollAnimation';
import { DEMO_MODE, DEMO_CONNECT_DELAY_MS } from '../demoConfig';

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// Same backend the mission console uses, so a connection established here
// carries over to the console screen unchanged.
const API_URL = 'http://localhost:8002';

class CanvasErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="canvas-fallback">
          <Satellite size={40} />
          <p>3D viewport unavailable</p>
        </div>
      );
    }
    return this.props.children;
  }
}

const CAPABILITIES = [
  { icon: ScanSearch, title: 'Advanced Search', desc: 'AI-powered object detection and thermal imaging for rapid target identification in all weather conditions', a: 'Detection Range', av: '2km', b: 'Accuracy', bv: '98.5%' },
  { icon: RadioTower, title: 'Real-time Comms', desc: 'Secure communication channels with ground control and rescue teams using encrypted protocols', a: 'Latency', av: '50ms', b: 'Encryption', bv: 'AES-256' },
  { icon: Crosshair, title: 'Precision Navigation', desc: 'GPS-guided autonomous flight with obstacle avoidance and predictive path planning', a: 'GPS Accuracy', av: '±1m', b: 'Obstacles', bv: 'Auto-avoid' },
  { icon: Zap, title: 'Rapid Deployment', desc: 'Quick launch capability for emergency response scenarios with automated pre-flight checks', a: 'Setup Time', av: '30sec', b: 'Ready State', bv: 'Always' },
  { icon: ShieldCheck, title: 'Weather Resistant', desc: 'All-weather operation capability with reinforced frame and weather protection systems', a: 'Wind Resistance', av: '15m/s', b: 'IP Rating', bv: 'IP43' },
  { icon: BrainCircuit, title: 'AI Integration', desc: 'Machine learning algorithms for pattern recognition and autonomous decision making', a: 'Processing', av: 'Real-time', b: 'Learning', bv: 'Adaptive' },
];

// Real Ryze / DJI Tello hardware specifications.
const SPECS = [
  {
    icon: Rocket, title: 'Flight Performance', items: [
      ['Max speed', '8 m/s'], ['Flight time', '13 min'], ['Max distance', '100 m'], ['Max altitude', '30 m'],
    ],
  },
  {
    icon: Cpu, title: 'Camera & Sensors', items: [
      ['Video', '720p HD'], ['Photo', '5 MP'], ['Field of view', '82.6°'], ['Stabilization', 'EIS'],
    ],
  },
  {
    icon: Gauge, title: 'Physical', items: [
      ['Weight', '80 g'], ['Dimensions', '98×92.5×41 mm'], ['Operating', '0–40 °C'], ['Battery', '1100 mAh'],
    ],
  },
];

// Icon per drone component (keyed by the component id from the 3D model).
const COMPONENT_ICONS = {
  propellers: Fan,
  motors: Cylinder,
  body: Box,
  camera: Camera,
  casing: Shield,
  branding: Tag,
};

// Logical part counts shown on each row (the GLB packs several physical parts
// into a single mesh, so the raw mesh count isn't meaningful here).
const COMPONENT_COUNT = {
  propellers: 4,
  motors: 4,
  body: 1,
  camera: 1,
  casing: 1,
  branding: 1,
};

// Draggable, glassy panel that lists the drone's components. Hovering a row
// highlights the matching part on the 3D model.
function ComponentsPanel({ components, onHover }) {
  const [pos, setPos] = useState({ x: 18, y: 18 });
  const [expanded, setExpanded] = useState(false);
  const drag = useRef(null);

  useEffect(() => {
    const onMove = (e) => {
      if (!drag.current) return;
      setPos({
        x: Math.max(0, drag.current.px + (e.clientX - drag.current.mx)),
        y: Math.max(0, drag.current.py + (e.clientY - drag.current.my)),
      });
    };
    const onUp = () => { drag.current = null; };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, []);

  const onDown = (e) => {
    drag.current = { mx: e.clientX, my: e.clientY, px: pos.x, py: pos.y };
    e.preventDefault();
  };

  if (!components.length) return null;

  const toggle = (e) => {
    e.stopPropagation();
    setExpanded((v) => !v);
    onHover(null);
  };

  return (
    <div className={`dc-panel glass ${expanded ? 'expanded' : 'collapsed'}`} style={{ left: pos.x, top: pos.y }}>
      <div className="dc-head" onPointerDown={onDown}>
        <GripVertical size={15} className="dc-grip" />
        <span className="dc-title">Drone components</span>
        <span className="dc-count-badge">{components.length}</span>
        <button
          type="button"
          className="dc-toggle"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={toggle}
          aria-label={expanded ? 'Collapse' : 'Expand'}
          title={expanded ? 'Collapse' : 'Show components'}
        >
          <ChevronDown size={15} />
        </button>
      </div>

      {expanded && (
        <>
          <div className="dc-list" onPointerLeave={() => onHover(null)}>
            {components.map((c) => {
              const Icon = COMPONENT_ICONS[c.id] || Box;
              return (
                <button
                  key={c.id}
                  className="dc-row"
                  onPointerEnter={() => onHover(c.id)}
                  onFocus={() => onHover(c.id)}
                  onBlur={() => onHover(null)}
                >
                  <span className="dc-ico"><Icon size={15} /></span>
                  <span className="dc-name">{c.label}</span>
                  <span className="dc-count">{COMPONENT_COUNT[c.id] ?? c.count}</span>
                </button>
              );
            })}
          </div>
          <div className="dc-foot">Hover a part to highlight it</div>
        </>
      )}
    </div>
  );
}

export default function LandingPage({ onStartMission }) {
  const { scrollY } = useScrollAnimation();
  const [isConnecting, setIsConnecting] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [droneData, setDroneData] = useState({
    status: 'DISCONNECTED', is_flying: false, position: { x: 0, y: 0, z: 0 },
    attitude: { pitch: 0, roll: 0, yaw: 0 }, altitude: 0, max_altitude: 30,
    speed: { vx: 0, vy: 0, vz: 0 }, battery: 0, temperature: 0,
  });

  // drone components (from the 3D model) + which one is hover-highlighted
  const [components, setComponents] = useState([]);
  const [highlightId, setHighlightId] = useState(null);

  // subtle live drift on the telemetry preview numbers
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1400);
    return () => clearInterval(id);
  }, []);

  const handleConnect = async () => {
    if (isConnecting) return;

    if (isConnected) {
      // Disconnect from the real backend (skipped in DEMO mode).
      if (!DEMO_MODE) {
        try {
          await fetch(`${API_URL}/drone/disconnect`, { method: 'POST' });
        } catch (error) {
          console.error('Disconnect error:', error);
        }
      }
      setIsConnected(false);
      setDroneData((p) => ({ ...p, status: 'DISCONNECTED', is_flying: false }));
      return;
    }

    setIsConnecting(true);

    // DEMO MODE: connect artificially, no backend required.
    if (DEMO_MODE) {
      await wait(DEMO_CONNECT_DELAY_MS);
      setIsConnected(true);
      setDroneData((p) => ({ ...p, status: 'CONNECTED', battery: 87, temperature: 42, altitude: 1.4, attitude: { ...p.attitude, yaw: 34 } }));
      setIsConnecting(false);
      return;
    }

    try {
      const response = await fetch(`${API_URL}/drone/connect`, { method: 'POST' });
      const data = await response.json();
      if (data.success) {
        setIsConnected(true);
        setDroneData((p) => ({
          ...p,
          status: 'CONNECTED',
          battery: typeof data.battery === 'number' ? data.battery : p.battery,
          temperature: typeof data.temperature === 'number' ? data.temperature : p.temperature,
        }));
      } else {
        console.error('Connection failed:', data.message);
      }
    } catch (error) {
      console.error('Connection error:', error);
    } finally {
      setIsConnecting(false);
    }
  };

  const startOperation = () => {
    if (isConnected && typeof onStartMission === 'function') onStartMission();
  };

  const drift = (base, amp) => (base + Math.sin(tick * 0.9 + base) * amp).toFixed(1);

  const connState = isConnecting ? 'connecting' : isConnected ? 'connected' : 'idle';

  return (
    <div className="app-shell landing">
      <ScrollProgress />
      <Navbar onLaunch={isConnected ? startOperation : handleConnect} connected={isConnected} />

      {/* ── HERO ─────────────────────────────────────────────────────── */}
      <section className="hero">
        <div className="hero-grid">
          <div className="hero-copy">
            <Reveal className="eyebrow" delay={80}>
              <span className="dot" /> Autonomous Search &amp; Rescue
            </Reveal>

            <Reveal delay={160}>
              <h1 className="hero-title">
                <span className="text-grad">NEXT-GEN</span> DRONE
              </h1>
            </Reveal>

            <Reveal delay={220}>
              <div className="hero-wordmark" data-text="HAWKOPS">HAWKOPS</div>
            </Reveal>

            <Reveal delay={300}>
              <p className="hero-desc">
                Precision drone technology for critical missions. Rapid search and
                rescue operations inside dangerous or burning buildings to find victims
                and protect crews, powered by advanced autonomous navigation.
              </p>
            </Reveal>

            <Reveal delay={340}>
              <div className="hero-actions">
                <button className={`connect-btn ${connState}`} onClick={handleConnect} disabled={isConnecting}>
                  <span className="connect-icon">
                    {connState === 'connected' ? <PlugZap size={18} /> : <Plug size={18} />}
                  </span>
                  <span>{isConnecting ? 'Establishing link…' : isConnected ? 'Linked' : 'Connect drone'}</span>
                  <span className="connect-dot" />
                </button>

                <button className={`btn btn-accent btn-shine launch-btn ${!isConnected ? 'is-locked' : ''}`} onClick={startOperation} disabled={!isConnected}>
                  Try live demo <ArrowUpRight size={17} />
                </button>
              </div>
            </Reveal>

            <Reveal delay={440}>
              <div className="hero-stats">
                <div className="hstat">
                  <div className="hstat-num"><Counter target={99.7} decimals={1} suffix="%" /></div>
                  <div className="hstat-label">Mission success</div>
                </div>
                <div className="hstat-div" />
                <div className="hstat">
                  <div className="hstat-num">24/7</div>
                  <div className="hstat-label">Operational</div>
                </div>
                <div className="hstat-div" />
                <div className="hstat">
                  <div className="hstat-num"><Counter target={13} suffix=" min" /></div>
                  <div className="hstat-label">Autonomy</div>
                </div>
              </div>
            </Reveal>
          </div>

          {/* 3D stage + floating glass cards */}
          <div className="hero-stage">
            <div className="stage-glow" />
            <div className="drone-scene">
              <CanvasErrorBoundary>
                <Canvas shadows style={{ width: '100%', height: '100%' }}>
                  <PerspectiveCamera makeDefault position={[0, 8, 0]} fov={125} />
                  <OrbitControls
                    enablePan={false} enableZoom={false}
                    maxPolarAngle={Math.PI / 2} minPolarAngle={0}
                    autoRotate autoRotateSpeed={0.5}
                  />
                  <LightingSetup />
                  <DroneModel
                    scrollY={scrollY}
                    isConnected={isConnected}
                    highlightId={highlightId}
                    onComponentsReady={setComponents}
                  />
                  <ParticleField />
                </Canvas>
              </CanvasErrorBoundary>
              <HUD isActive droneData={droneData} isConnected={isConnected} />
            </div>

            <ComponentsPanel components={components} onHover={setHighlightId} />
          </div>
        </div>

        <div className="hero-scrollcue">
          <span /> scroll
        </div>
      </section>

      {/* ── CAPABILITIES ─────────────────────────────────────────────── */}
      <section className="section" id="capabilities">
        <Reveal className="section-head" delay={0}>
          <span className="eyebrow"><span className="dot" /> Capabilities</span>
          <h2 className="section-title">Mission Capabilities</h2>
        </Reveal>

        <div className="cap-grid">
          {CAPABILITIES.map((c, i) => (
            <Reveal key={c.title} delay={i * 80} y={34}>
              <article className="cap-card glass">
                <div className="cap-ico"><c.icon size={20} /></div>
                <h3>{c.title}</h3>
                <p>{c.desc}</p>
                <div className="cap-stats">
                  <span>{c.a} <b>{c.av}</b></span>
                  <span>{c.b} <b>{c.bv}</b></span>
                </div>
                <div className="cap-sheen" />
              </article>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ── TELEMETRY BAND ───────────────────────────────────────────── */}
      <section className="section narrow" id="telemetry">
        <Reveal>
          <div className="telemetry-band glass-strong">
            <div className="tb-left">
              <span className="eyebrow"><span className="dot" /> Live telemetry</span>
              <h2 className="tb-title">Every frame, every reading —<br />streamed to the console.</h2>
              <p className="tb-desc">
                Battery, attitude, depth and AI hazard scoring update continuously while
                the autopilot sweeps each room. No blind spots, no guesswork.
              </p>
              <button className="btn btn-accent btn-shine" onClick={isConnected ? startOperation : handleConnect}>
                {isConnected ? 'Open the console' : 'Connect to preview'} <ArrowUpRight size={16} />
              </button>
            </div>
            <div className="tb-right">
              {[
                { ico: BatteryMedium, k: 'Battery', v: isConnected ? '87%' : '—' },
                { ico: Gauge, k: 'Core temp', v: isConnected ? '42°C' : '—' },
                { ico: Activity, k: 'Vert. speed', v: isConnected ? `${drift(2, 0.5)} m/s` : '—' },
                { ico: Satellite, k: 'GPS lock', v: isConnected ? 'Locked' : '—' },
                { ico: Crosshair, k: 'Heading', v: isConnected ? '034°' : '—' },
                { ico: ScanSearch, k: 'Hazard AI', v: isConnected ? 'Scanning' : '—' },
              ].map((m) => (
                <div className="tb-metric glass" key={m.k}>
                  <m.ico size={16} />
                  <div>
                    <div className="tbm-k">{m.k}</div>
                    <div className="tbm-v">{m.v}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Reveal>
      </section>

      {/* ── SPECS ────────────────────────────────────────────────────── */}
      <section className="section" id="specs">
        <Reveal className="section-head">
          <span className="eyebrow"><span className="dot" /> Specifications</span>
          <h2 className="section-title">The hardware behind the mission.</h2>
        </Reveal>

        <div className="spec-grid">
          {SPECS.map((s, i) => (
            <Reveal key={s.title} delay={i * 100} y={30}>
              <div className="spec-card glass">
                <div className="spec-head">
                  <span className="spec-ico"><s.icon size={18} /></span>
                  <h3>{s.title}</h3>
                </div>
                <div className="spec-items">
                  {s.items.map(([k, v]) => (
                    <div className="spec-row" key={k}>
                      <span>{k}</span>
                      <b>{v}</b>
                    </div>
                  ))}
                </div>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ── DEPLOY CTA ───────────────────────────────────────────────── */}
      <section className="section narrow" id="deploy">
        <Reveal>
          <div className="deploy glass-strong">
            <div className="deploy-glow" />
            <span className="eyebrow"><span className="dot" /> Deploy</span>
            <h2>Ready when the call comes.</h2>
            <p>Spin up HawkOps for your next critical operation — link the drone and step into the command console.</p>
            <div className="deploy-actions">
              <button className={`btn btn-accent btn-shine ${!isConnected ? 'is-locked' : ''}`} onClick={startOperation} disabled={!isConnected}>
                Deploy now <Rocket size={16} />
              </button>
              {!isConnected && (
                <button className="btn btn-ghost" onClick={handleConnect} disabled={isConnecting}>
                  {isConnecting ? 'Linking…' : 'Connect first'}
                </button>
              )}
            </div>
          </div>
        </Reveal>
      </section>

      <footer className="footer">
        <div className="footer-brand">
          <span className="nav-name">HAWKOPS</span>
          <span className="footer-tag">Autonomous drone command · mock build</span>
        </div>
        <div className="footer-links">
          <a href="#capabilities">Capabilities</a>
          <a href="#specs">Specs</a>
          <a href="#deploy">Deploy</a>
        </div>
      </footer>

      <style>{`
        .landing { position: relative; }

        /* ── HERO ── */
        .hero { position: relative; min-height: 100vh; display: flex; align-items: center; padding: 120px 6vw 60px; z-index: 1; }
        .hero-grid { width: 100%; max-width: 1480px; margin: 0 auto; display: grid; grid-template-columns: 1.05fr 1.25fr; gap: 40px; align-items: center; }
        .hero-copy { max-width: 600px; }
        .hero-title {
          font-family: var(--font-display); font-weight: 700;
          font-size: clamp(2.6rem, 5vw, 4.6rem); line-height: 1.02;
          letter-spacing: -1px; margin: 22px 0 0;
        }
        .hero-faint { color: var(--text-faint); }
        .hero-wordmark {
          position: relative;
          font-family: var(--font-display); font-weight: 700;
          font-size: clamp(3.6rem, 8.5vw, 7rem); line-height: 0.9;
          letter-spacing: clamp(2px, 1vw, 10px); margin: 14px 0 0;
          background: linear-gradient(120deg, #fff 0%, var(--accent-bright) 45%, var(--accent-teal) 100%);
          -webkit-background-clip: text; background-clip: text;
          -webkit-text-fill-color: transparent; color: transparent;
          filter: drop-shadow(0 6px 30px rgba(47,227,139,0.28));
        }
        .hero-wordmark::after {
          content: attr(data-text);
          position: absolute; inset: 0; z-index: -1;
          -webkit-text-fill-color: transparent;
          -webkit-text-stroke: 1px rgba(47,227,139,0.18);
          letter-spacing: inherit;
        }
        .hero-desc { color: var(--text-dim); font-size: 1.08rem; line-height: 1.65; margin: 24px 0 30px; max-width: 520px; }
        .hero-actions { display: flex; gap: 14px; flex-wrap: wrap; align-items: center; }

        .connect-btn {
          display: inline-flex; align-items: center; gap: 10px;
          padding: 0.78rem 1.3rem; border-radius: 999px; cursor: pointer;
          font-family: var(--font-sans); font-weight: 600; font-size: 0.92rem;
          background: var(--glass-2); color: var(--text);
          border: 1px solid var(--stroke); outline: none;
          transition: all 0.4s cubic-bezier(0.34,1.56,0.64,1);
        }
        .connect-btn .connect-icon { display: grid; place-items: center; opacity: 0.9; }
        .connect-btn .connect-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-faint); transition: all 0.4s ease; }
        .connect-btn.idle:hover { transform: translateY(-2px); border-color: var(--stroke-strong); background: rgba(255,255,255,0.07); }
        .connect-btn.connecting { border-color: rgba(255,183,77,0.5); color: var(--warn); background: rgba(255,183,77,0.08); }
        .connect-btn.connecting .connect-dot { background: var(--warn); box-shadow: 0 0 10px var(--warn); animation: dotPulse 1s ease-in-out infinite; }
        .connect-btn.connected { border-color: rgba(47,227,139,0.5); color: var(--accent); background: rgba(47,227,139,0.08); box-shadow: 0 0 24px -6px var(--accent-glow); }
        .connect-btn.connected .connect-dot { background: var(--accent); box-shadow: 0 0 10px var(--accent); }
        .connect-btn:disabled { cursor: wait; }

        .launch-btn.is-locked { opacity: 0.45; }
        .launch-btn { padding: 0.78rem 1.4rem; }

        .hero-stats { display: flex; align-items: center; gap: 26px; margin-top: 40px; }
        .hstat-num { font-family: var(--font-display); font-size: 1.7rem; font-weight: 700; color: #fff; }
        .hstat-label { font-size: 0.78rem; color: var(--text-faint); letter-spacing: 0.5px; margin-top: 2px; }
        .hstat-div { width: 1px; height: 34px; background: var(--stroke); }

        .hero-stage { position: relative; height: 78vh; min-height: 560px; }
        .stage-glow {
          position: absolute; inset: 6% 8%; border-radius: 50%;
          background: radial-gradient(circle, rgba(47,227,139,0.16), transparent 65%);
          filter: blur(30px); z-index: 0;
        }
        .drone-scene { position: absolute; inset: 0; border-radius: 28px; overflow: hidden; z-index: 1; }
        .canvas-fallback { width: 100%; height: 100%; display: grid; place-items: center; gap: 10px; color: var(--accent); }

        /* draggable components panel */
        .dc-panel { position: absolute; z-index: 6; width: 222px; padding: 0; overflow: hidden; user-select: none; animation: riseIn 0.5s cubic-bezier(0.22,1,0.36,1); }
        .dc-head { display: flex; align-items: center; gap: 8px; padding: 11px 13px; cursor: grab; border-bottom: 1px solid var(--stroke); touch-action: none; }
        .dc-head:active { cursor: grabbing; }
        .dc-panel.collapsed .dc-head { border-bottom: none; }
        .dc-grip { color: var(--text-faint); flex-shrink: 0; }
        .dc-title { font-size: 0.84rem; font-weight: 600; color: var(--text); }
        .dc-count-badge { margin-left: auto; font-family: var(--font-mono); font-size: 0.7rem; color: var(--text-faint); background: var(--glass); border: 1px solid var(--stroke); border-radius: 999px; padding: 1px 8px; }
        .dc-toggle { width: 25px; height: 25px; border-radius: 8px; display: grid; place-items: center; cursor: pointer; background: var(--glass-2); border: 1px solid var(--stroke); color: var(--text-dim); flex-shrink: 0; transition: all 0.2s ease; }
        .dc-toggle:hover { color: var(--accent); border-color: rgba(47,227,139,0.4); background: rgba(47,227,139,0.1); }
        .dc-toggle svg { transition: transform 0.28s cubic-bezier(0.22,1,0.36,1); }
        .dc-panel.expanded .dc-toggle svg { transform: rotate(180deg); }
        .dc-list { padding: 8px; display: flex; flex-direction: column; gap: 3px; }
        .dc-row {
          display: flex; align-items: center; gap: 11px; width: 100%;
          padding: 9px 10px; border-radius: 12px; cursor: pointer; text-align: left;
          background: transparent; border: 1px solid transparent; color: var(--text-dim);
          transition: all 0.18s ease;
        }
        .dc-row:hover { background: rgba(47,227,139,0.1); border-color: rgba(47,227,139,0.3); color: var(--text); }
        .dc-ico { width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center; background: var(--glass-2); border: 1px solid var(--stroke); color: var(--accent); flex-shrink: 0; transition: all 0.18s ease; }
        .dc-row:hover .dc-ico { background: rgba(47,227,139,0.15); border-color: rgba(47,227,139,0.4); box-shadow: 0 0 16px -6px var(--accent-glow); }
        .dc-name { font-size: 0.84rem; font-weight: 500; }
        .dc-count { margin-left: auto; font-family: var(--font-mono); font-size: 0.72rem; color: var(--text-faint); background: var(--glass); border: 1px solid var(--stroke); border-radius: 999px; padding: 1px 8px; }
        .dc-foot { padding: 9px 13px; font-size: 0.68rem; color: var(--text-faint); border-top: 1px solid var(--stroke); text-align: center; }

        .hero-scrollcue { position: absolute; bottom: 26px; left: 50%; transform: translateX(-50%); display: flex; flex-direction: column; align-items: center; gap: 8px; font-size: 0.7rem; letter-spacing: 2px; text-transform: uppercase; color: var(--text-faint); }
        .hero-scrollcue span { width: 1px; height: 32px; background: linear-gradient(var(--accent), transparent); }

        /* ── SECTIONS ── */
        .section { position: relative; z-index: 1; padding: 90px 6vw; max-width: 1480px; margin: 0 auto; }
        .section.narrow { max-width: 1200px; }
        .section-head { margin-bottom: 48px; }
        .section-title { font-family: var(--font-display); font-weight: 700; font-size: clamp(1.9rem, 3.4vw, 3rem); line-height: 1.08; letter-spacing: -0.5px; margin: 16px 0 0; }

        .cap-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; }
        .cap-card { padding: 26px; height: 100%; overflow: hidden; transition: transform 0.35s cubic-bezier(0.22,1,0.36,1), border-color 0.35s ease, box-shadow 0.35s ease; }
        .cap-card:hover { transform: translateY(-6px); border-color: rgba(47,227,139,0.4); box-shadow: 0 30px 60px -30px var(--accent-glow); }
        .cap-ico { width: 46px; height: 46px; border-radius: 14px; display: grid; place-items: center; background: rgba(47,227,139,0.1); border: 1px solid rgba(47,227,139,0.22); color: var(--accent); margin-bottom: 18px; }
        .cap-card h3 { font-size: 1.15rem; margin: 0 0 8px; font-weight: 600; }
        .cap-card p { color: var(--text-dim); font-size: 0.92rem; line-height: 1.6; margin: 0 0 20px; }
        .cap-stats { display: flex; gap: 18px; font-size: 0.78rem; color: var(--text-faint); border-top: 1px solid var(--stroke); padding-top: 16px; }
        .cap-stats b { color: var(--accent); font-weight: 600; margin-left: 4px; }
        .cap-sheen { position: absolute; top: -40%; left: -30%; width: 60%; height: 180%; background: linear-gradient(100deg, transparent, rgba(255,255,255,0.05), transparent); transform: skewX(-18deg); transition: left 0.7s ease; }
        .cap-card:hover .cap-sheen { left: 130%; }

        /* ── TELEMETRY BAND ── */
        .telemetry-band { display: grid; grid-template-columns: 1fr 1fr; gap: 36px; padding: 44px; align-items: center; overflow: hidden; }
        .tb-title { font-family: var(--font-display); font-weight: 700; font-size: clamp(1.6rem, 2.6vw, 2.2rem); line-height: 1.1; margin: 16px 0 16px; }
        .tb-desc { color: var(--text-dim); line-height: 1.65; margin-bottom: 26px; max-width: 420px; }
        .tb-right { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        .tb-metric { display: flex; align-items: center; gap: 12px; padding: 16px; color: var(--accent); }
        .tbm-k { font-size: 0.74rem; color: var(--text-faint); }
        .tbm-v { font-size: 1.05rem; font-weight: 600; color: var(--text); margin-top: 2px; font-family: var(--font-mono); }

        /* ── SPECS ── */
        .spec-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; }
        .spec-card { padding: 28px; }
        .spec-head { display: flex; align-items: center; gap: 12px; margin-bottom: 22px; }
        .spec-ico { width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; background: rgba(47,227,139,0.1); border: 1px solid rgba(47,227,139,0.22); color: var(--accent); }
        .spec-head h3 { font-size: 1.1rem; font-weight: 600; margin: 0; }
        .spec-items { display: flex; flex-direction: column; gap: 2px; }
        .spec-row { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid var(--stroke); }
        .spec-row:last-child { border-bottom: none; }
        .spec-row span { color: var(--text-dim); font-size: 0.92rem; }
        .spec-row b { color: var(--text); font-family: var(--font-mono); font-size: 0.92rem; }

        /* ── DEPLOY ── */
        .deploy { position: relative; text-align: center; padding: 60px 40px; overflow: hidden; }
        .deploy-glow { position: absolute; top: -60%; left: 50%; transform: translateX(-50%); width: 600px; height: 600px; background: radial-gradient(circle, rgba(47,227,139,0.14), transparent 60%); filter: blur(20px); }
        .deploy h2 { position: relative; font-family: var(--font-display); font-weight: 700; font-size: clamp(2rem, 3.6vw, 3rem); margin: 18px 0 14px; }
        .deploy p { position: relative; color: var(--text-dim); max-width: 520px; margin: 0 auto 30px; line-height: 1.6; }
        .deploy-actions { position: relative; display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }
        .is-locked { opacity: 0.45; }

        /* ── FOOTER ── */
        .footer { position: relative; z-index: 1; max-width: 1480px; margin: 0 auto; padding: 40px 6vw 60px; display: flex; justify-content: space-between; align-items: center; border-top: 1px solid var(--stroke); gap: 20px; flex-wrap: wrap; }
        .footer-brand { display: flex; flex-direction: column; gap: 4px; }
        .footer-tag { color: var(--text-faint); font-size: 0.8rem; }
        .footer-links { display: flex; gap: 22px; }
        .footer-links a { color: var(--text-dim); text-decoration: none; font-size: 0.86rem; }
        .footer-links a:hover { color: var(--accent); }

        @media (max-width: 1080px) {
          .hero-grid { grid-template-columns: 1fr; gap: 24px; }
          .hero-stage { height: 64vh; order: -1; }
          .cap-grid, .spec-grid { grid-template-columns: 1fr 1fr; }
          .telemetry-band { grid-template-columns: 1fr; }
        }
        @media (max-width: 720px) {
          .hero { padding: 110px 5vw 40px; }
          .cap-grid, .spec-grid, .tb-right { grid-template-columns: 1fr; }
          .float-card { display: none; }
          .hero-stats { flex-wrap: wrap; gap: 16px; }
        }
      `}</style>
    </div>
  );
}

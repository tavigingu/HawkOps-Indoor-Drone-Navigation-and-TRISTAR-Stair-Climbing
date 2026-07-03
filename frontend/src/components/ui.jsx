import React, { useEffect, useState, useRef } from 'react';
import { useScrollAnimation, useFadeInOnScroll } from '../hooks/useScrollAnimation';

// Reveal-on-scroll wrapper with directional offset + stagger.
export function Reveal({ children, delay = 0, y = 28, x = 0, className = '', as = 'div' }) {
  const [ref, visible] = useFadeInOnScroll(0.12);
  const Tag = as;
  return (
    <Tag
      ref={ref}
      className={className}
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? 'none' : `translate(${x}px, ${y}px)`,
        transition: `opacity 0.8s cubic-bezier(0.22,1,0.36,1) ${delay}ms, transform 0.8s cubic-bezier(0.22,1,0.36,1) ${delay}ms`,
        willChange: 'opacity, transform',
      }}
    >
      {children}
    </Tag>
  );
}

// Count-up number, triggered when scrolled into view.
export function Counter({ target, duration = 1600, suffix = '', decimals = 0 }) {
  const [ref, visible] = useFadeInOnScroll(0.4);
  const [value, setValue] = useState(0);
  const started = useRef(false);

  useEffect(() => {
    if (!visible || started.current) return;
    started.current = true;
    let raf;
    let start;
    const tick = (t) => {
      if (!start) start = t;
      const p = Math.min((t - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      setValue(target * eased);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [visible, target, duration]);

  return (
    <span ref={ref}>
      {value.toFixed(decimals)}
      {suffix}
    </span>
  );
}

// Thin top scroll-progress bar.
export function ScrollProgress() {
  const { scrollProgress } = useScrollAnimation();
  return (
    <div
      style={{
        position: 'fixed', top: 0, left: 0, height: 2, zIndex: 1200,
        width: `${scrollProgress}%`,
        background: 'linear-gradient(90deg, var(--accent), var(--accent-teal))',
        boxShadow: '0 0 12px var(--accent-glow)',
        transition: 'width 0.1s linear',
      }}
    />
  );
}

// Frosted floating pill navbar (matches the reference, refined).
export function Navbar({ onLaunch, connected }) {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <nav className={`nav-wrap ${scrolled ? 'nav-scrolled' : ''}`}>
      <div className="nav-pill glass-strong">
        <div className="nav-brand">
          <span className="nav-logo">
            <svg width="20" height="20" viewBox="0 0 32 32" fill="none">
              <path d="M16 5l8 6-3 1.1L16 9l-5 3.1L8 11l8-6z" fill="var(--accent)" />
              <path d="M8 13l5 3L16 23l3-7 5-3-1.6 8L16 27l-6.4-6L8 13z" fill="var(--accent)" opacity="0.85" />
            </svg>
          </span>
          <span className="nav-name">HAWKOPS</span>
        </div>
        <div className="nav-links">
          <a href="#capabilities">Capabilities</a>
          <a href="#telemetry">Telemetry</a>
          <a href="#specs">Specs</a>
          <a href="#deploy">Deploy</a>
        </div>
        <button className="btn btn-accent btn-shine nav-cta" onClick={onLaunch}>
          {connected ? 'Open Console' : 'Get started'}
        </button>
      </div>

      <style>{`
        .nav-wrap {
          position: fixed; top: 18px; left: 0; right: 0;
          display: flex; justify-content: center; z-index: 1000;
          padding: 0 18px; transition: top 0.3s ease;
        }
        .nav-pill {
          display: flex; align-items: center; gap: 28px;
          padding: 9px 9px 9px 22px; border-radius: 999px;
          width: min(880px, 100%);
        }
        .nav-scrolled .nav-pill { box-shadow: 0 18px 50px -20px rgba(0,0,0,0.8); }
        .nav-brand { display: flex; align-items: center; gap: 10px; }
        .nav-logo {
          width: 34px; height: 34px; display: grid; place-items: center;
          border-radius: 50%; background: rgba(47,227,139,0.1);
          border: 1px solid rgba(47,227,139,0.25);
        }
        .nav-name { font-family: var(--font-display); font-weight: 700; letter-spacing: 2px; font-size: 0.95rem; }
        .nav-links { display: flex; gap: 26px; margin-left: auto; }
        .nav-links a {
          color: var(--text-dim); text-decoration: none; font-size: 0.88rem; font-weight: 500;
          transition: color 0.2s ease; position: relative;
        }
        .nav-links a:hover { color: var(--text); }
        .nav-links a::after {
          content: ''; position: absolute; left: 0; bottom: -6px; height: 1.5px; width: 0;
          background: var(--accent); transition: width 0.25s ease;
        }
        .nav-links a:hover::after { width: 100%; }
        .nav-cta { padding: 0.6rem 1.2rem; font-size: 0.86rem; }
        @media (max-width: 760px) {
          .nav-links { display: none; }
          .nav-pill { gap: 14px; padding-left: 18px; }
        }
      `}</style>
    </nav>
  );
}

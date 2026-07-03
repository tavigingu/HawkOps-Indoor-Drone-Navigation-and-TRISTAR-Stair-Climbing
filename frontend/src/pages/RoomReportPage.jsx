import React, { useEffect, useState } from 'react';
import { Flame, Cloud, User, Crosshair, AlertTriangle, CheckCircle2, ScanLine } from 'lucide-react';
import './RoomReportPage.css';

const API_URL = 'http://localhost:8002';

export default function RoomReportPage({ roomIndex, embedded = false, reportDataOverride = null }) {
  const [reportData, setReportData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (reportDataOverride) {
      setReportData(reportDataOverride);
      setLoading(false);
      setError(null);
      return;
    }

    let isMounted = true;
    const fetchReport = async () => {
      try {
        const response = await fetch(`${API_URL}/reports/live/${roomIndex}`);
        const data = await response.json();
        if (isMounted) {
          if (data?.success) { setReportData(data.report || null); setError(null); }
          else setError('Unable to load room report.');
        }
      } catch (err) {
        if (isMounted) setError('Failed to connect to the report server.');
      } finally {
        if (isMounted) setLoading(false);
      }
    };
    fetchReport();
    const interval = setInterval(fetchReport, 1200);
    return () => { isMounted = false; clearInterval(interval); };
  }, [roomIndex, reportDataOverride]);

  useEffect(() => {
    if (!reportDataOverride) return;
    setReportData(reportDataOverride);
    setLoading(false);
    setError(null);
  }, [reportDataOverride]);

  const label = reportData?.room_label || 'Awaiting label';
  const live = reportData?.live;
  const saved = reportData?.saved_report;
  const preEntry = reportData?.pre_entry_ai_analysis || live?.pre_entry_ai_analysis || saved?.pre_entry_ai_analysis || null;
  const hazardsLive = live?.hazards_counts || null;
  const hazardsSaved = saved?.hazards_detected || null;
  const personsDetails =
    Array.isArray(saved?.persons_details) && saved.persons_details.length > 0
      ? saved.persons_details
      : Array.isArray(live?.persons_details) ? live.persons_details : [];

  const resolveAssetUrl = (p) => {
    if (!p || typeof p !== 'string') return null;
    if (p.startsWith('http://') || p.startsWith('https://')) return p;
    return `${API_URL}${p}`;
  };

  const aiImageUrl = resolveAssetUrl(preEntry?.image_url);
  const ocrFrames = reportData?.ocr_frames || null;
  const ocrFullFrameUrl = resolveAssetUrl(ocrFrames?.full_frame_url);
  const preEntryStatus = preEntry?.status || (preEntry ? 'success' : 'pending');
  const hasPreEntryError = preEntryStatus === 'error';
  const preEntryStateText = hasPreEntryError ? 'Pre-entry AI error' : preEntryStatus === 'success' ? 'AI response received' : 'In progress…';

  const level = preEntry?.level || 'Unspecified';
  const levelTone = /high|danger|critical/i.test(level) ? 'danger' : /medium|warn/i.test(level) ? 'warn' : /low|safe/i.test(level) ? 'ok' : 'neutral';

  const fireOn = hazardsSaved ? hazardsSaved.fire : null;
  const smokeOn = hazardsSaved ? hazardsSaved.smoke : null;

  return (
    <div className={`rr ${embedded ? 'embedded' : ''}`}>
      <header className="rr-head">
        <div>
          <h1>{label}</h1>
          <span className="rr-sub">Room {roomIndex} · scan report</span>
        </div>
        <span className={`rr-level rr-${levelTone}`}>
          {levelTone === 'danger' ? <AlertTriangle size={14} /> : <ScanLine size={14} />} {level}
        </span>
      </header>

      {loading && <div className="rr-status">Loading room report data…</div>}
      {error && <div className="rr-error">{error}</div>}

      {!loading && !error && (
        <div className="rr-grid">
          <section className="rr-card rr-wide">
            <h2><Crosshair size={15} /> Pre-entry AI analysis</h2>
            <div className="rr-preentry">
              <div className="rr-img-box">
                {aiImageUrl ? (
                  <img src={aiImageUrl} alt={`Pre-entry ${roomIndex}`} className="rr-img" />
                ) : (
                  <div className="rr-img-empty"><ScanLine size={28} /><span>Image unavailable</span></div>
                )}
              </div>
              <div className="rr-preentry-text">
                <p>
                  <span className="rr-k">Status</span>
                  <span className={hasPreEntryError ? 'rr-bad' : 'rr-good'}>{preEntryStateText}</span>
                </p>
                <p><span className="rr-k">Level</span><span>{level}</span></p>
                <p className="rr-desc">{preEntry?.description || 'AI description is not available yet.'}</p>
                {preEntry?.request_id && <p><span className="rr-k">Request ID</span><span className="rr-mono">{preEntry.request_id}</span></p>}
                <p>
                  <span className="rr-k">Service</span>
                  <span>{preEntry?.response_received ? 'Responded' : 'No response'}{typeof preEntry?.http_status === 'number' ? ` · HTTP ${preEntry.http_status}` : ''}</span>
                </p>
                {preEntry?.error && <p className="rr-bad">{preEntry.error}</p>}
              </div>
            </div>
          </section>

          {ocrFullFrameUrl && (
            <section className="rr-card rr-wide">
              <h2><ScanLine size={15} /> OCR detection — full frame with bounding box</h2>
              <div className="rr-ocr-grid">
                <div className="rr-ocr-box">
                  <p className="rr-ocr-label">Captured frame (green box = detected label region)</p>
                  <img src={ocrFullFrameUrl} alt="OCR full frame with detection" className="rr-ocr-img" />
                </div>
              </div>
            </section>
          )}

          <section className="rr-card">
            <h2><Flame size={15} /> Fire &amp; smoke</h2>
            <div className="rr-hazards">
              <div className={`rr-hazard ${fireOn ? 'on' : fireOn === false ? 'off' : 'pending'}`}>
                <Flame size={18} />
                <span>Fire</span>
                <b>{fireOn == null ? 'In progress' : fireOn ? 'Detected' : 'Clear'}</b>
              </div>
              <div className={`rr-hazard ${smokeOn ? 'on' : smokeOn === false ? 'off' : 'pending'}`}>
                <Cloud size={18} />
                <span>Smoke</span>
                <b>{smokeOn == null ? 'In progress' : smokeOn ? 'Detected' : 'Clear'}</b>
              </div>
            </div>
            <div className="rr-frames">
              <span>Fire frames <b>{hazardsLive?.fire ?? 0}</b></span>
              <span>Smoke frames <b>{hazardsLive?.smoke ?? 0}</b></span>
            </div>
          </section>

          <section className="rr-card">
            <h2><User size={15} /> Detection summary</h2>
            <div className="rr-summary">
              <div><span>Persons</span><b>{live?.persons_detected ?? saved?.persons_detected ?? 0}</b></div>
              <div><span>Frames analyzed</span><b>{live?.frames_analyzed ?? saved?.frames_analyzed ?? 0}</b></div>
            </div>
          </section>

          <section className="rr-card rr-wide">
            <h2><User size={15} /> Person detections</h2>
            {personsDetails.length > 0 ? (
              <div className="rr-persons">
                {personsDetails.map((person) => {
                  const medical = person?.medical_analysis || null;
                  const medicalState = medical?.medical_state || 'UNKNOWN';
                  const indicators = Array.isArray(medical?.indicators) ? medical.indicators : [];
                  const tone = medicalState === 'CRITICAL' ? 'danger' : medicalState === 'STABLE' ? 'ok' : 'neutral';
                  return (
                    <div className="rr-person" key={person.track_id}>
                      <div className="rr-person-img">
                        {resolveAssetUrl(person.image_url) ? (
                          <img src={resolveAssetUrl(person.image_url)} alt={`Person ${person.track_id}`} />
                        ) : (
                          <div className="rr-person-noimg"><User size={22} /></div>
                        )}
                      </div>
                      <div className="rr-person-info">
                        <div className="rr-person-top">
                          <span className="rr-person-id">Track #{person.track_id}</span>
                          {person.posture && <span className="rr-tag">{person.posture}</span>}
                          <span className={`rr-medical rr-${tone}`}>{medicalState}</span>
                        </div>
                        <p className="rr-person-desc">{medical?.description || 'Medical analysis is not available.'}</p>
                        <div className="rr-person-meta">
                          <span>Confidence <b>{person.confidence}</b></span>
                          {person?.position?.region && <span>Position <b>{person.position.region}</b></span>}
                          {Array.isArray(person?.position?.center) && person.position.center.length === 2 && (
                            <span>Center <b>{person.position.center[0]}, {person.position.center[1]}</b></span>
                          )}
                        </div>
                        {indicators.length > 0 && (
                          <div className="rr-indicators">
                            {indicators.map((ind) => <span key={ind} className="rr-ind">{ind}</span>)}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="rr-empty"><CheckCircle2 size={20} /> No person detections for this room yet.</div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

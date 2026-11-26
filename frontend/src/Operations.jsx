import React, {useEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {
  Bot,
  Send,
  X,
  Maximize2,
  Minimize2,
  RotateCcw,
  Sparkles,
  GripHorizontal,
  Copy,
  Check,
  AlertTriangle,
  ChevronDown,
} from 'lucide-react';

export const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

async function request(path, options) {
  const response = await fetch(API + path, options);
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Request failed.');
  return data;
}

// Clean LaTeX math symbols, text wrappers, and broken tags from model output
function cleanLatexText(text) {
  if (!text) return '';
  let s = text;
  // Unwrap \text{...}
  s = s.replace(/\\text\{([^}]*)\}/g, '$1');
  // Standard math replacements
  s = s.replace(/\\approx/g, '~')
       .replace(/\\le/g, '<=')
       .replace(/\\ge/g, '>=')
       .replace(/\\times/g, 'x')
       .replace(/\\pm/g, '+/-')
       .replace(/\\cdot/g, '·')
       .replace(/\\degree/g, '°')
       .replace(/\\neq/g, '!=');
  // Unwrap math dollars ($$ ... $$ and $ ... $)
  s = s.replace(/\$\$([^$]+)\$\$/g, '$1');
  s = s.replace(/\$([^$]+)\$/g, '$1');
  // Clean broken partial tokens (e.g. '):t{ mg/L}', '\te', '\t{...}')
  s = s.replace(/:\s*t\{[^}]*\}/g, ':');
  s = s.replace(/\\te\b/g, '');
  s = s.replace(/\\t\{([^}]*)\}/g, '$1');
  s = s.replace(/\\([a-zA-Z]+)/g, '$1');
  s = s.replace(/\$/g, '');
  return s.trim();
}

// High-end Markdown, Table, and Structure Formatter for assistant turns
function FormattedContent({ text }) {
  const cleaned = cleanLatexText(text);
  const lines = cleaned.split('\n');
  const elements = [];
  let listItems = [];
  let isNumbered = false;

  function flushList() {
    if (listItems.length > 0) {
      if (isNumbered) {
        elements.push(<ol key={'ol-' + elements.length} className="chat-ol">{listItems}</ol>);
      } else {
        elements.push(<ul key={'ul-' + elements.length} className="chat-ul">{listItems}</ul>);
      }
      listItems = [];
      isNumbered = false;
    }
  }

  function renderInline(str) {
    if (!str) return '';
    const parts = [];
    const regex = /(\*\*[^*]+\*\*|`[^`]+`)/g;
    let lastIdx = 0;
    let match;

    while ((match = regex.exec(str)) !== null) {
      if (match.index > lastIdx) {
        parts.push(str.substring(lastIdx, match.index));
      }
      const token = match[0];
      if (token.startsWith('**') && token.endsWith('**')) {
        parts.push(<strong key={'b-' + match.index} className="chat-strong">{token.slice(2, -2)}</strong>);
      } else if (token.startsWith('`') && token.endsWith('`')) {
        parts.push(<code key={'c-' + match.index} className="chat-code">{token.slice(1, -1)}</code>);
      }
      lastIdx = regex.lastIndex;
    }
    if (lastIdx < str.length) {
      parts.push(str.substring(lastIdx));
    }
    return parts.length ? parts : str;
  }

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      flushList();
      i++;
      continue;
    }

    // Markdown Table Support: checks for | header | and next line |---|
    if (trimmed.startsWith('|') && trimmed.endsWith('|') && i + 1 < lines.length && /^\s*\|?\s*[-:]+[-| :]*\|\s*$/.test(lines[i + 1])) {
      flushList();
      const headers = trimmed.split('|').slice(1, -1).map(c => c.trim());
      i += 2; // skip header and separator row
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith('|') && lines[i].trim().endsWith('|')) {
        const cells = lines[i].trim().split('|').slice(1, -1).map(c => c.trim());
        rows.push(cells);
        i++;
      }
      elements.push(
        <div key={'table-' + i} className="chat-table-wrapper">
          <table className="chat-table">
            <thead>
              <tr>
                {headers.map((h, hIdx) => <th key={hIdx}>{renderInline(h)}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rIdx) => (
                <tr key={rIdx}>
                  {row.map((cell, cIdx) => <td key={cIdx}>{renderInline(cell)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    if (trimmed.startsWith('### ')) {
      flushList();
      elements.push(<h4 key={'h4-' + i} className="chat-h4">{renderInline(trimmed.slice(4))}</h4>);
    } else if (trimmed.startsWith('## ')) {
      flushList();
      elements.push(<h3 key={'h3-' + i} className="chat-h3">{renderInline(trimmed.slice(3))}</h3>);
    } else if (trimmed.startsWith('# ')) {
      flushList();
      elements.push(<h2 key={'h2-' + i} className="chat-h2">{renderInline(trimmed.slice(2))}</h2>);
    } else if (trimmed === '---' || trimmed === '***') {
      flushList();
      elements.push(<hr key={'hr-' + i} className="chat-hr" />);
    } else if (trimmed.startsWith('* ') || trimmed.startsWith('- ') || trimmed.startsWith('• ')) {
      if (isNumbered) flushList();
      const content = trimmed.replace(/^[\*\-•]\s+/, '');
      listItems.push(<li key={'li-' + i}>{renderInline(content)}</li>);
    } else if (/^\d+\.\s+/.test(trimmed)) {
      if (!isNumbered) flushList();
      isNumbered = true;
      const content = trimmed.replace(/^\d+\.\s+/, '');
      listItems.push(<li key={'li-' + i}>{renderInline(content)}</li>);
    } else {
      flushList();
      elements.push(<p key={'p-' + i} className="chat-p">{renderInline(trimmed)}</p>);
    }
    i++;
  }

  flushList();
  return <div className="chat-formatted">{elements}</div>;
}

const DEFAULT_CHAT_SIZE = { width: 528, height: 696 };

export function Assistant() {
  const [open, setOpen] = useState(false);
  const [maximized, setMaximized] = useState(false);
  const [turns, setTurns] = useState([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [copiedIdx, setCopiedIdx] = useState(null);
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  // Draggable position and Resizable dimensions
  const [pos, setPos] = useState({ x: null, y: null });
  const [size, setSize] = useState(DEFAULT_CHAT_SIZE);

  const end = useRef(null);
  const conversationRef = useRef(null);

  // Position initialized on open near the bottom-left launcher.
  useEffect(() => {
    if (open && pos.x === null) {
      const w = Math.min(DEFAULT_CHAT_SIZE.width, window.innerWidth - 32);
      const h = Math.min(DEFAULT_CHAT_SIZE.height, window.innerHeight - 32);
      setPos({
        x: 16,
        y: Math.max(16, window.innerHeight - h - 30),
      });
      setSize({ width: w, height: h });
    }
  }, [open]);

  // Viewport bounds check
  useEffect(() => {
    function handleResize() {
      setPos(p => {
        if (p.x === null) return p;
        const maxX = Math.max(10, window.innerWidth - size.width - 10);
        const maxY = Math.max(10, window.innerHeight - size.height - 10);
        return {
          x: Math.min(Math.max(10, p.x), maxX),
          y: Math.min(Math.max(10, p.y), maxY),
        };
      });
    }
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [size]);

  // Dragging logic
  function startDrag(e) {
    if (maximized) return;
    if (e.target.closest('button') || e.target.closest('input')) return;

    e.preventDefault();
    const startX = e.clientX;
    const startY = e.clientY;
    const startPosX = pos.x ?? 16;
    const startPosY = pos.y ?? Math.max(16, window.innerHeight - size.height - 30);

    function onPointerMove(moveEvent) {
      const dx = moveEvent.clientX - startX;
      const dy = moveEvent.clientY - startY;
      const maxX = Math.max(10, window.innerWidth - size.width - 10);
      const maxY = Math.max(10, window.innerHeight - size.height - 10);
      setPos({
        x: Math.min(Math.max(10, startPosX + dx), maxX),
        y: Math.min(Math.max(10, startPosY + dy), maxY),
      });
    }

    function onPointerUp() {
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
    }

    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
  }

  // Resizing logic
  function startResize(e) {
    if (maximized) return;
    e.preventDefault();
    e.stopPropagation();

    const startX = e.clientX;
    const startY = e.clientY;
    const startW = size.width;
    const startH = size.height;

    function onPointerMove(moveEvent) {
      const dw = moveEvent.clientX - startX;
      const dh = moveEvent.clientY - startY;
      const minW = 340;
      const maxW = Math.min(940, window.innerWidth - (pos.x || 0) - 10);
      const minH = 400;
      const maxH = Math.min(900, window.innerHeight - (pos.y || 0) - 10);

      setSize({
        width: Math.min(Math.max(minW, startW + dw), Math.max(minW, maxW)),
        height: Math.min(Math.max(minH, startH + dh), Math.max(minH, maxH)),
      });
    }

    function onPointerUp() {
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
    }

    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
  }

  function scrollToBottom(smooth = false) {
    if (conversationRef.current) {
      conversationRef.current.scrollTo({
        top: conversationRef.current.scrollHeight + 1000,
        behavior: smooth ? 'smooth' : 'auto',
      });
    }
  }

  function handleScroll() {
    if (!conversationRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = conversationRef.current;
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 80;
    setShowScrollBtn(!isNearBottom);
  }

  useEffect(() => {
    scrollToBottom(false);
    const t1 = setTimeout(() => scrollToBottom(true), 60);
    const t2 = setTimeout(() => scrollToBottom(true), 250);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [open, turns, busy, error]);

  async function send(customText) {
    const message = (typeof customText === 'string' ? customText : input).trim();
    if (!message || busy) return;
    setInput('');
    setTurns(prev => [...prev, { role: 'user', text: message }]);
    setBusy(true);
    setError('');
    try {
      const historyPayload = [...turns, { role: 'user', text: message }]
        .slice(-8)
        .map(({ role, text }) => ({ role, text: (text || '').slice(0, 12000) }));

      const result = await request('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          history: historyPayload,
        }),
      });
      setTurns(prev => [
        ...prev,
        { role: 'model', text: result.reply, time: result.time_s },
      ]);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function copyTurn(idx, text) {
    navigator.clipboard.writeText(cleanLatexText(text));
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx(null), 2000);
  }

  const promptChips = [
    { label: '📊 Effluent BOD/COD', query: 'What are the current effluent BOD, COD, and TSS levels? Are they meeting target references?' },
    { label: '⚠️ Active Alarms', query: 'List all active alarms and explain their potential process causes and recommended actions.' },
    { label: '🔬 4 BNR Trains', query: 'Compare the 4 biological trains (Anaerobic, Pre-anoxic, Aerobic, Post-anoxic). Are they operating identically?' },
    { label: '⚡ Energy & Aeration', query: 'What is our current cumulative energy consumption and blower aeration intensity?' },
    { label: '💧 Membrane & Fouling', query: 'What is the current membrane TMP and fouling status across the 4 MBR trains?' },
  ];

  return (
    <aside className="assistant">
      {open && createPortal(
        <section
          className={`assistant-panel ${maximized ? 'maximized' : ''}`}
          style={!maximized && pos.x !== null ? { left: `${pos.x}px`, top: `${pos.y}px`, width: `${size.width}px`, height: `${size.height}px` } : {}}
          aria-label="Plant AI Assistant"
        >
          {/* Header Bar: Draggable handle & control buttons */}
          <header className="assistant-header" onPointerDown={startDrag}>
            <div className="assistant-header-title">
              <span className="drag-grip" title="Drag to move panel">
                <GripHorizontal size={15} />
              </span>
              <span className="status-ping" />
              <strong>PLANT AI ASSISTANT</strong>
              <span className="ai-badge">BNR–MBR</span>
            </div>

            <div className="assistant-header-actions">
              <button
                type="button"
                className="icon-btn"
                onClick={() => setTurns([])}
                title="Clear conversation"
              >
                <RotateCcw size={13} />
              </button>
              <button
                type="button"
                className="icon-btn"
                onClick={() => setMaximized(!maximized)}
                title={maximized ? 'Restore size' : 'Maximize window'}
              >
                {maximized ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
              </button>
              <button
                type="button"
                className="icon-btn close-btn"
                onClick={() => setOpen(false)}
                title="Close chat"
              >
                <X size={15} />
              </button>
            </div>
          </header>

          {/* Prompt chips */}
          <div className="assistant-chips">
            {promptChips.map((chip, idx) => (
              <button
                key={idx}
                type="button"
                className="chip-btn"
                disabled={busy}
                onClick={() => send(chip.query)}
              >
                {chip.label}
              </button>
            ))}
          </div>

          {/* Conversation history area */}
          <div className="conversation" ref={conversationRef} onScroll={handleScroll} role="log" aria-label="Assistant conversation" tabIndex={0}>
            {!turns.length && (
              <div className="chat-empty-state">
                <div className="chat-empty-icon">
                  <Bot size={28} />
                </div>
                <h3>Intelligent SCADA Assistant</h3>
                <p>
                  Ask about effluent quality, biological train kinetics, alarms, membrane fouling, or control tuning.
                </p>
                <span className="chat-empty-hint">Click any quick prompt above or type below.</span>
              </div>
            )}

            {turns.map((t, i) => (
              t.role === 'user' ? (
                <article key={i} className="turn-bubble user">
                  <div className="user-bubble-text">{t.text}</div>
                </article>
              ) : (
                <article key={i} className="turn-bubble model">
                  <div className="turn-meta">
                    <span className="turn-author">AI Assistant</span>
                    {t.time !== undefined && (
                      <span className="turn-time">t = {t.time} s</span>
                    )}
                    <button
                      type="button"
                      className="copy-btn"
                      onClick={() => copyTurn(i, t.text)}
                      title="Copy response"
                    >
                      {copiedIdx === i ? <Check size={12} /> : <Copy size={12} />}
                      <span>{copiedIdx === i ? 'Copied' : 'Copy'}</span>
                    </button>
                  </div>
                  <div className="turn-body">
                    <FormattedContent text={t.text} />
                  </div>
                </article>
              )
            ))}

            {busy && (
              <div className="chat-thinking">
                <span className="pulse-dot" />
                <span className="pulse-dot" />
                <span className="pulse-dot" />
                <span>Reading simulation telemetry & synthesizing diagnostic…</span>
              </div>
            )}

            {error && (
              <div className="chat-error-banner" role="alert">
                <AlertTriangle size={15} />
                <span>{error}</span>
              </div>
            )}

            <div className="chat-bottom-spacer" ref={end} />
          </div>

          {showScrollBtn && (
            <button
              type="button"
              className="jump-bottom-btn"
              onClick={() => scrollToBottom(true)}
              title="Scroll to latest messages"
            >
              <ChevronDown size={14} />
              <span>Scroll to latest</span>
            </button>
          )}

          {/* Input Form */}
          <form
            className="assistant-input-form"
            onSubmit={e => {
              e.preventDefault();
              send();
            }}
          >
            <input
              aria-label="Question"
              placeholder="Ask about plant kinetics, effluent, alarms, or controls…"
              value={input}
              disabled={busy}
              maxLength={2000}
              onChange={e => setInput(e.target.value)}
            />
            <button
              type="submit"
              className="send-btn"
              disabled={busy || !input.trim()}
              title="Send message"
            >
              <Send size={15} />
            </button>
          </form>

          {/* Bottom-right corner resize handle */}
          {!maximized && (
            <div
              className="assistant-resize-handle"
              onPointerDown={startResize}
              title="Drag to resize panel"
            />
          )}
        </section>,
        document.body
      )}

      {!open && (
        <button
          className="assistant-fab"
          aria-expanded={open}
          aria-label="Plant Assistant"
          onClick={() => setOpen(value=>!value)}
        >
          <div className="fab-glow" />
          <span aria-hidden="true">🤖</span>
          <span>PLANT ASSISTANT</span>
          <span className="fab-dot" />
        </button>
      )}
    </aside>
  );
}

const colors = ['#41d3ff','#ffcb77','#70e0b7'];
function Trend({rows, series, unit}) {
  const width=560, height=100;
  const points=rows.map(r=>series.map(s=>s.value(r.snapshot)));
  let max=1;
  for (const values of points) for(const v of values) max=Math.max(v,max);
  const start=rows[0].time_s, finish=rows.at(-1).time_s;
  const x=i=>4+(width-8)*(rows[i].time_s-start)/(finish-start || 1);
  const y=v=>height-4-(height-8)*v/max;
  // Preserve each time bucket's minimum and maximum when rendering long runs.
  function indices(j) {
    const selected=new Set();
    const buckets=new Map();
    rows.forEach((r,i)=>{
      if (points[i][j] == null) {
        if (points[i-1]?.[j] != null) {
          selected.add(i-1);
          selected.add(i);
        }
        return;
      }
      if (points[i-1]?.[j] == null) selected.add(i);
      const k=Math.floor(x(i)), b=buckets.get(k)||[i,i];
      if(points[i][j]<points[b[0]][j]) b[0]=i;
      if(points[i][j]>points[b[1]][j]) b[1]=i;
      buckets.set(k,b);
    });
    for(const [a,b] of buckets.values()) {
      selected.add(a);
      selected.add(b);
    }
    if (points.at(-1)[j] != null) selected.add(rows.length-1);
    return [...selected].sort((a,b)=>a-b);
  }
  return <figure><figcaption>{series.map((s,j)=><span key={s.name} style={{color:colors[j]}}>{s.name} </span>)}· {unit}</figcaption>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={series.map(s=>s.name).join(', ')+' over simulated time'}>
    {series.map((s,j)=><g key={s.name}><path fill="none" stroke={colors[j]} strokeWidth="2" d={indices(j).map(i=>points[i][j] == null ? '' : `${points[i-1]?.[j] == null ? 'M' : 'L'}${x(i)},${y(points[i][j])}`).join(' ')}/>{points.at(-1)[j] != null && <circle cx={x(rows.length-1)} cy={y(points.at(-1)[j])} r="3" fill={colors[j]}/>}</g>)}</svg>
    <small>{start}–{finish} simulated s · vertical scale 0–{Number(max.toFixed(2))} {unit}</small></figure>;
}

function Detail({run}) {
  const hasDischargeData = run.effluent_basis === 'discharge';
  const finalSample = Object.entries(run.final_effluent).filter(([,value])=>value != null);
  return <section><h3>Session analytics</h3>
    {hasDischargeData ? <>
      <p>{finalSample.length ? finalSample.map(([k,v])=>k.toUpperCase()+' '+v+' mg/L').join(' · ') : 'No discharge in the final interval.'}</p>
      <Trend rows={run.steps} series={['cod','bod','tss'].map(k=>({name:k.toUpperCase(),value:s=>s.effluent_quality?.[k] ?? null}))} unit="mg/L"/>
    </> : <p>This session predates discharge-quality recording.</p>}
    <Trend rows={run.steps} series={[{name:'Cumulative energy',value:s=>s.energy_kwh}]} unit="kWh"/>
    <Trend rows={run.steps} series={[{name:'Treated flow',value:s=>s.flows_gpm.treated_out || 0}]} unit="GPM"/>
    <h3>Alarm timeline</h3>{run.total_alerts_triggered===0 && <p>No alarms triggered.</p>}
    {run.steps.flatMap((s,i)=>s.new_alerts.map(a=><div key={i+a}>{s.time_s} s · {a}</div>))}</section>;
}

export function History({close}) {
  const [runs, setRuns]=useState(null), [detail,setDetail]=useState(null), [error,setError]=useState(''), [busy,setBusy]=useState(false);
  useEffect(()=>{const controller=new AbortController();
    request('/history',{signal:controller.signal}).then(setRuns).catch(e=>{if(!controller.signal.aborted)setError(e.message)});
    return ()=>controller.abort();
  },[]);
  async function action(run, remove) {
    if(remove && !window.confirm('Delete this recorded session?')) return;
    setBusy(true); setError('');
    const path='/history/'+run.session_id;
    try {
      if(remove) {
        await request(path,{method:'DELETE'});
        setRuns(r=>r.filter(x=>x.session_id!==run.session_id));
        if(detail?.session_id===run.session_id)setDetail(null);
      } else setDetail(await request(path));
    } catch(e) {setError(e.message)} finally {setBusy(false)}
  }
  return <div className="tab-overlay"><section className="tab-card archive"><div className="overlay-head"><b>Simulation history</b><button onClick={close}>Close ×</button></div>
    {error && <p role="alert">{error}</p>}{!runs && !error && <p>Loading sessions…</p>}
    {runs?.length===0 && <p>Run the simulation, then select Reset to save your first session.</p>}
    {runs?.map(r=><article className="run" key={r.session_id}><strong>{new Date(r.started_at).toLocaleString()}</strong><small>{r.status} · {r.total_steps} steps · {r.total_simulated_seconds} s · {r.total_energy_kwh} kWh · {r.total_alerts_triggered} alarms</small>
      <div><button disabled={busy} onClick={()=>action(r,false)}>View</button> <a href={API+'/history/'+r.session_id+'/download'}>Download CSV</a> <button disabled={busy} onClick={()=>action(r,true)}>Delete</button></div></article>)}
    {busy && <p role="status">Loading…</p>}{detail && <Detail run={detail}/>}</section></div>;
}

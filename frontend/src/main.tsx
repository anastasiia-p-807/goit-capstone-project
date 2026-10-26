import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BookOpen, Feather, ChartNoAxesColumnIncreasing, Library, FlaskConical, Plus, Search, ArrowUpRight, LogOut, Trash2, ChevronLeft, ChevronRight, Check, Leaf } from 'lucide-react';
import './style.css';

type User = { id: string; username: string };
type Resource = { id: string; title: string; author: string; kind: string; description: string; topics: string[]; url: string; color: string; reason?: string };
type Analysis = { status: string; emotions: { label: string; score: number }[]; model_version: string | null };
type Entry = { id: string; title: string; content: string; entry_date: string; mood: number | null; topic: string | null; analysis: Analysis; recommendations: Resource[] };
type Draft = Pick<Entry, 'title' | 'content' | 'entry_date' | 'mood' | 'topic'>;
type Summary = { entries: number; writing_days: number; emotions: { label: string; count: number }[]; days: { date: string; mood: number | null; check_ins: number }[] };
type Status = { model_ready: boolean; registration_open: boolean };
type Page = 'journal' | 'insights' | 'library' | 'demo';
const topics = ['stress', 'self-compassion', 'worry', 'sleep'];
const moods = ['Very low', 'Low', 'Okay', 'Good', 'Very good'];
const nice = (s: string) => s.replaceAll('-', ' ').replace(/^./, c => c.toUpperCase());
const dateLabel = (s: string) => new Date(s + 'T12:00:00').toLocaleDateString('en', { month: 'short', day: 'numeric', year: 'numeric' });
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const blank = (): Draft => ({ title: '', content: '', entry_date: today(), mood: null, topic: null });

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch('/api' + path, { ...options, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Still-Client': 'web', ...options.headers } });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 && !path.startsWith('/auth')) window.dispatchEvent(new Event('session-expired'));
    const detail = data.detail;
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((e: { msg: string; loc: string[] }) => `${e.loc.at(-1)}: ${e.msg}`).join(' · ') : `Request failed (${response.status}). Please try again.`);
  }
  return response.status === 204 ? undefined as T : response.json();
}

function ErrorBox({ message, retry }: { message: string; retry?: () => void }) {
  return <div className="error" role="alert">{message}{retry && <button className="text-button" onClick={retry}>Try again</button>}</div>;
}
function ResourceCard({ item }: { item: Resource }) {
  return <article className={'resource-card ' + item.color}>
    <div className="resource-top"><BookOpen size={25} /><span>{item.kind}</span></div>
    <h3>{item.title}</h3><p className="author">{item.author}</p><p>{item.description}</p>
    {item.reason && <p className="reason">{item.reason}</p>}
    <a href={item.url} target="_blank" rel="noopener noreferrer">Open resource <ArrowUpRight size={16} /><span className="sr-only"> (opens in a new tab)</span></a>
  </article>;
}
function AnalysisView({ analysis, recommendations }: { analysis: Analysis; recommendations: Resource[] }) {
  return <section className="reflection"><div className="section-title"><Leaf size={19} /><h3>{analysis.status === 'demo' ? 'Example reflection' : 'Your reflection'}</h3></div>
    {analysis.status === 'demo' && <p className="demo-note">DEMO · Handwritten labels and scores, not model predictions.</p>}
    {analysis.status === 'unavailable' && <p className="muted">Your words are saved. Emotion analysis is not connected yet. You can still track your own mood and choose a reading topic.</p>}
    {analysis.status === 'uncertain' && <p className="muted">No clear emotion was identified in this entry. Your own interpretation comes first.</p>}
    {analysis.emotions.length > 0 && <><div className="emotion-tags">{analysis.emotions.map(e => <span key={e.label}>{nice(e.label)} <b>{Math.round(e.score * 100)}%</b></span>)}</div><p className="small muted">Scores are classifier outputs, not a diagnosis or a measure of how strongly you feel.</p></>}
    {recommendations.length > 0 && <div className="recommended">{recommendations.map(r => <ResourceCard key={r.id} item={r} />)}</div>}
  </section>;
}

function Auth({ onUser, registration, onDemo }: { onUser: (u: User) => void; registration: boolean; onDemo: () => void }) {
  const [register, setRegister] = useState(false);
  const [username, setUsername] = useState(''); const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError('');
    try { const result = await api<{ user: User }>('/auth/' + (register ? 'register' : 'login'), { method: 'POST', body: JSON.stringify({ username, password }) }); onUser(result.user); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <div className="welcome"><section className="welcome-story"><div className="eyebrow">A LITTLE SPACE FOR YOURSELF</div><h1>Slow down.<br />Let it out.<br /><em>Find your still.</em></h1><p>A quiet place to put your day into words, notice how you feel, and find something worth reading.</p><div className="welcome-illustration"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><Feather size={72} strokeWidth={1} /></div><button className="text-button" onClick={onDemo}>Explore an example reflection <ArrowUpRight size={17} /></button></section>
    <section className="auth-card"><span className="eyebrow">YOUR JOURNAL, YOUR PACE</span><h2>{register ? 'Make a little space.' : 'Welcome back.'}</h2><p className="muted">{register ? 'Create an account to start your own journal.' : 'Sign in and pick up where you left off.'}</p>
      <form onSubmit={submit}><label>Username<input autoComplete="username" required minLength={3} maxLength={32} pattern="[a-zA-Z0-9_-]+" value={username} onChange={e => setUsername(e.target.value)} /></label><p className="field-hint">3–32 letters, numbers, underscores or hyphens.</p><label>Password<input type="password" autoComplete={register ? 'new-password' : 'current-password'} required minLength={10} maxLength={128} value={password} onChange={e => setPassword(e.target.value)} /></label><p className="field-hint">At least 10 characters.</p>{error && <ErrorBox message={error} />}<button className="primary full" disabled={busy}>{busy ? 'Please wait…' : register ? 'Create account' : 'Sign in'} <ArrowUpRight size={18} /></button></form>
      {registration && <p className="auth-switch">{register ? 'Already have an account?' : 'New to Still?'} <button className="text-button" disabled={busy} onClick={() => { setRegister(!register); setError(''); }}>{register ? 'Sign in' : 'Create an account'}</button></p>}
      <p className="small muted">Entries are stored on the server running this app. This prototype has no password recovery; keep your credentials somewhere safe.</p>
    </section></div>;
}

function Journal({ onDirty }: { onDirty: (dirty: boolean) => void }) {
  const [entries, setEntries] = useState<Entry[]>([]); const [total, setTotal] = useState(0);
  const [q, setQ] = useState(''); const [search, setSearch] = useState(''); const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Entry | null>(null); const [draft, setDraft] = useState<Draft>(blank);
  const [baseline, setBaseline] = useState(() => JSON.stringify(draft));
  const dirty = JSON.stringify(draft) !== baseline;
  const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false);
  const [error, setError] = useState(''); const [listError, setListError] = useState(''); const [message, setMessage] = useState(''); const [revision, setRevision] = useState(0);
  useEffect(() => { onDirty(dirty); return () => onDirty(false); }, [dirty, onDirty]);
  useEffect(() => { const t = setTimeout(() => { setSearch(q); setOffset(0); }, 250); return () => clearTimeout(t); }, [q]);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setListError('');
    api<{ items: Entry[]; total: number }>(`/entries?q=${encodeURIComponent(search)}&limit=8&offset=${offset}`, { signal: controller.signal }).then(data => { setEntries(data.items); setTotal(data.total); if (offset > 0 && data.items.length === 0) setOffset(Math.max(0, offset - 8)); }).catch(e => { if (!controller.signal.aborted) setListError(e.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [search, offset, revision]);
  function open(item: Entry | null) {
    if (busy || (dirty && !window.confirm('Discard your unsaved changes?'))) return;
    const next = item ? { title: item.title, content: item.content, entry_date: item.entry_date, mood: item.mood, topic: item.topic } : blank();
    setSelected(item); setDraft(next); setBaseline(JSON.stringify(next)); setError(''); setMessage('');
  }
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(''); setMessage('');
    try {
      const item = await api<Entry>(selected ? `/entries/${selected.id}` : '/entries', { method: selected ? 'PUT' : 'POST', body: JSON.stringify(draft) });
      const next = { title: item.title, content: item.content, entry_date: item.entry_date, mood: item.mood, topic: item.topic };
      setSelected(item); setDraft(next); setBaseline(JSON.stringify(next)); setRevision(n => n + 1); setMessage('Your entry is saved.');
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function remove() {
    if (!selected || !window.confirm('Permanently delete this entry? This cannot be undone.')) return;
    setBusy(true); setError('');
    try { await api(`/entries/${selected.id}`, { method: 'DELETE' }); const next = blank(); setSelected(null); setDraft(next); setBaseline(JSON.stringify(next)); setRevision(n => n + 1); setMessage('Entry deleted.'); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <><div className="page-heading"><div><div className="eyebrow">ONE DAY AT A TIME</div><h1>Your journal</h1><p>A few words can make a little room.</p></div><button className="primary" onClick={() => open(null)} disabled={busy}><Plus size={18} /> New entry</button></div>
  <div className="journal-grid"><aside className="entry-list"><label className="search"><Search size={18} /><input aria-label="Search entries" placeholder="Search your words…" maxLength={200} value={q} onChange={e => setQ(e.target.value)} /></label><div className="list-heading"><span>{total} {total === 1 ? 'entry' : 'entries'}</span><span>NEWEST FIRST</span></div>
    {loading ? <p className="list-message" role="status">Loading your journal…</p> : listError ? <ErrorBox message={listError} retry={() => setRevision(n => n + 1)} /> : entries.length === 0 ? <div className="empty-list"><Feather size={28} /><h3>{search ? 'No matching entries' : 'Your story starts here'}</h3><p>{search ? 'Try a different word or clear your search.' : 'Write your first entry. There is no perfect way to begin.'}</p></div> : entries.map(item => <button disabled={busy} className={'entry-item ' + (selected?.id === item.id ? 'selected' : '')} key={item.id} onClick={() => open(item)}><span className="entry-date">{dateLabel(item.entry_date)}{item.mood && <span className={'mood-dot mood-' + item.mood} title={moods[item.mood - 1]} />}</span><strong>{item.title}</strong><span className="excerpt">{item.content}</span>{item.topic && <span className="topic-pill">{nice(item.topic)}</span>}</button>)}
    {total > 8 && <div className="pagination"><button aria-label="Previous page" disabled={offset === 0 || loading} onClick={() => setOffset(n => n - 8)}><ChevronLeft size={18} /></button><span>{Math.floor(offset / 8) + 1} / {Math.ceil(total / 8)}</span><button aria-label="Next page" disabled={offset + 8 >= total || loading} onClick={() => setOffset(n => n + 8)}><ChevronRight size={18} /></button></div>}
  </aside><section className="editor-card"><form onSubmit={save}><fieldset disabled={busy}><div className="editor-toolbar"><span className="eyebrow">{selected ? 'YOUR ENTRY' : 'A FRESH PAGE'}</span><label className="date-input"><span className="sr-only">Entry date</span><input type="date" required value={draft.entry_date} onChange={e => setDraft({ ...draft, entry_date: e.target.value })} /></label></div>
    <label><span className="sr-only">Entry title</span><input className="title-input" placeholder="Give today a title…" maxLength={120} value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })} /></label>
    <label><span className="sr-only">Journal entry (English)</span><textarea className="writing-area" required maxLength={10000} placeholder="What's taking up space in your mind? Start wherever you are." value={draft.content} onChange={e => setDraft({ ...draft, content: e.target.value })} /></label><div className="writing-footer"><span>English entries · A title is optional</span><span>{draft.content.length.toLocaleString()} / 10,000</span></div>
    <div className="check-in"><h3>How are you feeling?</h3><p className="small muted">Your own check-in. Optional, and separate from emotion analysis.</p><div className="mood-options">{moods.map((label, i) => <button type="button" key={label} aria-pressed={draft.mood === i + 1} className={draft.mood === i + 1 ? 'active' : ''} onClick={() => setDraft({ ...draft, mood: draft.mood === i + 1 ? null : i + 1 })}><span className={'mood-face face-' + (i + 1)}>{['◡', '–', '·', '⌣', '⌣'][i]}</span>{label}</button>)}</div></div>
    <label className="topic-select">A reading direction <span className="muted">(optional)</span><select value={draft.topic || ''} onChange={e => setDraft({ ...draft, topic: e.target.value || null })}><option value="">No topic selected</option>{topics.map(t => <option key={t} value={t}>{nice(t)}</option>)}</select></label>
    <div className="save-row"><span className="small muted">{dirty ? 'Unsaved changes' : selected ? 'Saved to your journal' : 'A little honesty is enough.'}</span><div>{selected && <button className="icon-button danger" type="button" aria-label="Delete entry" onClick={remove}><Trash2 size={18} /></button>}<button className="primary" disabled={!draft.content.trim()}>{busy ? 'Saving…' : <><Check size={17} /> Save entry</>}</button></div></div></fieldset></form>
    {error && <ErrorBox message={error} />}{message && <p className="success" role="status">{message}</p>}{selected && !dirty && <AnalysisView analysis={selected.analysis} recommendations={selected.recommendations} />}
  </section></div></>;
}

function Insights() {
  const [data, setData] = useState<Summary | null>(null); const [error, setError] = useState(''); const [revision, setRevision] = useState(0);
  useEffect(() => { const c = new AbortController(); setError(''); api<Summary>('/summary', { signal: c.signal }).then(setData).catch(e => { if (!c.signal.aborted) setError(e.message); }); return () => c.abort(); }, [revision]);
  return <><div className="page-heading"><div><div className="eyebrow">NOTICE THE LITTLE THINGS</div><h1>Your patterns, gently.</h1><p>A look at the days you made space for yourself.</p></div></div>{error ? <ErrorBox message={error} retry={() => setRevision(n => n + 1)} /> : !data ? <p role="status">Loading your insights…</p> : <><div className="stat-grid"><div><span>Words into moments</span><strong>{data.entries}</strong><p>journal entries</p></div><div><span>Showing up for yourself</span><strong>{data.writing_days}</strong><p>days with an entry</p></div><div><span>Checking in</span><strong>{data.days.reduce((n, d) => n + d.check_ins, 0)}</strong><p>self-reported mood check-ins</p></div></div>
    <div className="insight-grid"><section className="panel"><h2>Your mood over time</h2><p className="muted small">Daily averages of your own 1–5 check-ins. Showing the latest 30 writing days.</p>{data.days.length === 0 ? <p className="empty-copy">Save an entry and add a mood to begin seeing your patterns.</p> : <div className="mood-history">{data.days.slice(-30).reverse().map(d => <div className="mood-history-row" key={d.date}><span>{dateLabel(d.date)}</span><meter min={1} max={5} value={d.mood ?? 1} aria-label={`Mood on ${d.date}: ${d.mood ?? 'not recorded'}`} className={d.mood === null ? 'no-mood' : ''} /><b>{d.mood ?? '—'}</b></div>)}</div>}<p className="small muted">1 = very low · 5 = very good · — = no check-in</p></section>
    <section className="panel"><h2>Emotions in your words</h2><p className="muted small">Number of saved entries with each model label. Your mood ratings and demo examples are excluded.</p>{data.emotions.length === 0 ? <div className="empty-copy"><Leaf size={32} /><p>No emotion results yet. Your journal and mood tracking work without a connected model.</p></div> : data.emotions.map(e => <div className="emotion-count" key={e.label}><span>{nice(e.label)}</span><b>{e.count}</b></div>)}</section></div></>}
  </>;
}

function LibraryPage() {
  const [items, setItems] = useState<Resource[] | null>(null); const [filter, setFilter] = useState(''); const [error, setError] = useState(''); const [revision, setRevision] = useState(0);
  useEffect(() => { const c = new AbortController(); setError(''); api<{ items: Resource[] }>('/resources', { signal: c.signal }).then(d => setItems(d.items)).catch(e => { if (!c.signal.aborted) setError(e.message); }); return () => c.abort(); }, [revision]);
  return <><div className="page-heading"><div><div className="eyebrow">SOMETHING TO TAKE WITH YOU</div><h1>A little perspective.</h1><p>Guides and workbooks to explore at your own pace.</p></div></div><div className="filter-row">{['', ...topics].map(t => <button key={t} className={filter === t ? 'active' : ''} aria-pressed={filter === t} onClick={() => setFilter(t)}>{t ? nice(t) : 'All resources'}</button>)}</div>{error ? <ErrorBox message={error} retry={() => setRevision(n => n + 1)} /> : !items ? <p role="status">Loading resources…</p> : <div className="resource-grid">{items.filter(r => !filter || r.topics.includes(filter)).map(r => <ResourceCard key={r.id} item={r} />)}</div>}<p className="library-note">A small editorial collection. These resources offer general information, not personalised treatment.</p></>;
}

function DemoPage() {
  const [data, setData] = useState<{ items: Pick<Entry, 'id' | 'title' | 'content' | 'analysis' | 'recommendations'>[]; notice: string } | null>(null);
  const [selected, setSelected] = useState(0); const [error, setError] = useState(''); const [revision, setRevision] = useState(0);
  useEffect(() => { const c = new AbortController(); setError(''); api<NonNullable<typeof data>>('/demo', { signal: c.signal }).then(setData).catch(e => { if (!c.signal.aborted) setError(e.message); }); return () => c.abort(); }, [revision]);
  const item = data?.items[selected];
  return <><div className="page-heading"><div><div className="eyebrow">A PREVIEW OF EMOTION ANALYSIS</div><h1>See a reflection.</h1><p>Explore what an analysis could look like.</p></div><span className="demo-badge">DEMO EXAMPLES</span></div>{error ? <ErrorBox message={error} retry={() => setRevision(n => n + 1)} /> : !data ? <p role="status">Loading examples…</p> : <><div className="demo-banner"><FlaskConical size={22} /><p>{data.notice}</p></div><div className="filter-row">{data.items.map((e, i) => <button key={e.id} className={selected === i ? 'active' : ''} aria-pressed={selected === i} onClick={() => setSelected(i)}>{e.title}</button>)}</div>{item && <article className="demo-entry panel"><span className="eyebrow">FICTIONAL JOURNAL ENTRY</span><h2>{item.title}</h2><p className="demo-content">{item.content}</p><AnalysisView analysis={item.analysis} recommendations={item.recommendations} /></article>}</>}</>;
}

function App() {
  const [user, setUser] = useState<User | null>(null); const [status, setStatus] = useState<Status | null>(null); const [ready, setReady] = useState(false);
  const [error, setError] = useState(''); const [page, setPage] = useState<Page>('journal'); const [dirty, setDirty] = useState(false);
  const [revision, setRevision] = useState(0); const [loggingOut, setLoggingOut] = useState(false);
  useEffect(() => { const c = new AbortController(); setError(''); setReady(false);
    Promise.all([api<Status>('/status', { signal: c.signal }), fetch('/api/auth/me', { signal: c.signal, credentials: 'same-origin' }).then(async r => { if (r.status === 401) return null; if (!r.ok) throw new Error('Could not check your session.'); return (await r.json()).user as User; })]).then(([s, u]) => { setStatus(s); setUser(u); setReady(true); }).catch(e => { if (!c.signal.aborted) setError(e.message); }); return () => c.abort();
  }, [revision]);
  useEffect(() => { const expire = () => { setError('Your session expired. Copy any unsaved text before signing out and back in. Your draft remains on this page.'); }; window.addEventListener('session-expired', expire); return () => window.removeEventListener('session-expired', expire); }, []);
  useEffect(() => { const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } }; window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn); }, [dirty]);
  function navigate(next: Page) { if (next === page || (dirty && !window.confirm('Discard your unsaved changes?'))) return; setDirty(false); setPage(next); }
  async function logout() { if (dirty && !window.confirm('Discard unsaved changes and sign out?')) return; setLoggingOut(true); try { await api('/auth/logout', { method: 'POST' }); setUser(null); setPage('journal'); setDirty(false); } catch (e) { setError((e as Error).message); } finally { setLoggingOut(false); } }
  const nav = [{ id: 'journal', label: 'Journal', icon: Feather }, { id: 'insights', label: 'Insights', icon: ChartNoAxesColumnIncreasing }, { id: 'library', label: 'Reading room', icon: Library }, { id: 'demo', label: 'ML examples', icon: FlaskConical }] as const;
  return <div className="app"><header className="app-header"><a className="brand" href="#" onClick={e => { e.preventDefault(); navigate('journal'); }}><span className="brand-mark"><Feather size={25} strokeWidth={1.5} /></span>still<span className="brand-dot">.</span></a>{user && <nav aria-label="Main navigation">{nav.map(n => <button key={n.id} className={page === n.id ? 'active' : ''} aria-current={page === n.id ? 'page' : undefined} onClick={() => navigate(n.id)}><n.icon size={17} />{n.label}</button>)}</nav>}<div className="account">{user ? <><span className="username">{user.username}</span><button className="icon-button" aria-label="Sign out" disabled={loggingOut} onClick={logout}><LogOut size={18} /></button></> : page === 'demo' && <button className="secondary" onClick={() => setPage('journal')}>Back to sign in</button>}</div></header>
    <main className={'main ' + (!user && page !== 'demo' ? 'auth-main' : '')}>{error && <ErrorBox message={error} retry={!ready ? () => setRevision(n => n + 1) : undefined} />}{!ready ? !error && <p role="status">Opening your space…</p> : !user && page !== 'demo' ? <Auth registration={status?.registration_open ?? true} onUser={u => { setUser(u); setError(''); setPage('journal'); }} onDemo={() => setPage('demo')} /> : <>{user && <div className="workspace-note"><span className="status-dot" />{status?.model_ready ? 'Emotion model connected' : 'Journal ready · Emotion model not connected'}<span>YOUR OWN PACE, ALWAYS</span></div>}{page === 'journal' && user ? <Journal onDirty={setDirty} /> : page === 'insights' && user ? <Insights /> : page === 'library' && user ? <LibraryPage /> : <DemoPage />}</>}</main><footer className="app-footer"><span>Still Journal</span><span>A space for reflection. Not a clinical assessment.</span><span>Take your time.</span></footer></div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);

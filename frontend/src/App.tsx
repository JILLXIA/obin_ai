import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { ArrowDown, ArrowRight, ArrowUp, BookOpen, Check, ChevronRight, CircleHelp, FileText, LoaderCircle, PanelRight, Plus, RefreshCw, Search, ShieldCheck, X } from 'lucide-react'
import { ApiError, ask, getDocument, getHealth } from './api'
import type { Citation, DocumentInfo, Health, Rect, Turn } from './types'

const QUESTIONS = [
  { category: 'FINANCIAL PERFORMANCE', question: 'What were Apple’s total net sales in 2023?' },
  { category: 'BUSINESS OVERVIEW', question: 'What are Apple’s reportable business segments?' },
  { category: 'REVENUE', question: 'How does Apple recognize revenue from its products?' },
  { category: 'PEOPLE', question: 'How many full-time employees did Apple have?' },
]
const EMPTY_RECTS: Rect[] = []
const PdfViewer = lazy(() => import('./PdfViewer'))
const STATUS_LABELS = { answered: 'From the filing', partial: 'Partially supported', insufficient_evidence: 'More evidence needed', needs_clarification: 'A little more context' }

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [documentInfo, setDocumentInfo] = useState<DocumentInfo | null>(null)
  const [connectionError, setConnectionError] = useState('')
  const [checking, setChecking] = useState(false)
  const [query, setQuery] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [busy, setBusy] = useState(false)
  const [citation, setCitation] = useState<Citation | null>(null)
  const [viewerPage, setViewerPage] = useState(1)
  const [viewerOpen, setViewerOpen] = useState(false)
  const [sourceOpen, setSourceOpen] = useState(false)
  const [showExcerpt, setShowExcerpt] = useState(false)
  const textarea = useRef<HTMLTextAreaElement>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const asideRef = useRef<HTMLElement>(null)
  const controller = useRef<AbortController | null>(null)

  const refresh = useCallback(async () => {
    setChecking(true)
    try {
      const [nextHealth, nextDocument] = await Promise.all([getHealth(), getDocument()])
      setHealth(nextHealth)
      setDocumentInfo(nextDocument)
      setConnectionError('')
    } catch (err) {
      setConnectionError(err instanceof Error ? err.message : 'Could not connect to the backend.')
    } finally { setChecking(false) }
  }, [])

  useEffect(() => { void refresh(); return () => controller.current?.abort() }, [refresh])
  useEffect(() => { endRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'end' }) }, [turns, busy])
  useEffect(() => { if (sourceOpen) asideRef.current?.focus() }, [sourceOpen, citation])

  async function submit(text: string, retryId?: string) {
    if (!text.trim() || busy || text.trim().length > 2000) return
    const id = retryId ?? crypto.randomUUID()
    const turn = { id, query: text.trim() }
    setTurns(previous => retryId ? previous.map(item => item.id === id ? turn : item) : [...previous, turn])
    setQuery('')
    setBusy(true)
    const abort = new AbortController()
    controller.current = abort
    const timeout = window.setTimeout(() => abort.abort(), 180000)
    try {
      const answer = await ask(turn.query, abort.signal)
      setTurns(previous => previous.map(item => item.id === id ? { ...item, answer } : item))
    } catch (err) {
      const message = err instanceof Error && err.name === 'AbortError'
        ? 'The request timed out. Please try again.'
        : err instanceof Error ? err.message : 'Something went wrong. Please retry.'
      setTurns(previous => previous.map(item => item.id === id ? { ...item, error: message, requestId: err instanceof ApiError ? err.requestId : undefined } : item))
    } finally {
      window.clearTimeout(timeout)
      setBusy(false)
      controller.current = null
      textarea.current?.focus()
    }
  }

  function openCitation(next: Citation) {
    setCitation(next)
    setViewerPage(next.pdf_page)
    setViewerOpen(true)
    setSourceOpen(true)
    setShowExcerpt(false)
  }

  function browse(page = 1) {
    setCitation(null)
    setViewerPage(page)
    setViewerOpen(true)
    setSourceOpen(true)
  }

  function closeSource() { setSourceOpen(false); textarea.current?.focus() }
  function onPanelKey(event: KeyboardEvent<HTMLElement>) {
    if (event.key === 'Escape') closeSource()
    if (event.key === 'Tab' && window.matchMedia('(max-width: 900px)').matches) {
      const targets = asideRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input, [tabindex="0"]')
      if (!targets?.length) return
      const first = targets[0], last = targets[targets.length - 1]
      if (event.shiftKey && (document.activeElement === first || document.activeElement === asideRef.current)) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
  }

  function onSubmit(event: FormEvent) { event.preventDefault(); void submit(query) }
  const ready = health?.status === 'ready' && !connectionError
  const highlights = citation?.pdf_page === viewerPage ? citation.highlight_rects : EMPTY_RECTS

  return <div className="app-shell">
    <header className="topbar">
      <a className="wordmark" href="/" aria-label="Filing home"><span className="logo-mark"><BookOpen size={19} strokeWidth={1.7} /></span>filing<span className="wordmark-dot">.</span></a>
      <span className="topbar-divider" />
      <span className="workspace-label">YOUR DOCUMENT WORKSPACE</span>
      <div className="topbar-right"><span className="local-badge"><span /> Local workspace</span><button className="icon-button mobile-source-button" aria-label="Open source document" onClick={() => { setSourceOpen(true) }}><PanelRight size={19} /></button></div>
    </header>

    <div className="workspace">
      <main className="chat-main">
        <div className="chat-toolbar"><div><span className="eyebrow">DOCUMENT CHAT</span><span className="toolbar-doc">Apple · 2023 Form 10-K</span></div><button className="quiet-button" disabled={!turns.length || busy} onClick={() => { setTurns([]); setCitation(null); textarea.current?.focus() }}><Plus size={15} /> New chat</button></div>
        <div className="conversation" aria-label="Conversation">
          {!turns.length && <div className="welcome">
            <div className="document-tag"><FileText size={14} /> ONE FILING. EVERY ANSWER IN CONTEXT.</div>
            <h1>Ask the filing.</h1>
            <p className="welcome-description">Get clear answers from Apple’s annual report,<br className="desktop-break" /> with the source always a click away.</p>
            <div className="question-grid">{QUESTIONS.map(({ category, question }) => <button className="question-card" key={question} disabled={busy} onClick={() => { setQuery(question); textarea.current?.focus() }}><span>{category}</span><strong>{question}</strong><ArrowUp className="question-arrow" size={16} /></button>)}</div>
            <div className="grounding-note"><ShieldCheck size={16} /><span>Answers grounded in this document. Sources included.</span></div>
          </div>}

          {turns.map(turn => <article className="turn" key={turn.id}>
            <div className="user-message"><span className="message-label">YOU</span><p>{turn.query}</p></div>
            {turn.answer && <div className="assistant-message"><div className="assistant-heading"><span className="small-logo"><BookOpen size={15} /></span><strong>Filing</strong><span className={`answer-status ${turn.answer.status}`}><span />{STATUS_LABELS[turn.answer.status]}</span></div>
              <div className="answer-text">{turn.answer.answer_blocks.map((block, index) => <p key={index}>{block.text}{block.citation_ids.map(id => {
                const source = turn.answer!.citations.find(item => item.id === id)
                return source ? <button key={id} className="inline-citation" aria-label={`View source ${id}, PDF page ${source.pdf_page}`} onClick={() => openCitation(source)}>{id}</button> : null
              })}</p>)}</div>
              {!!turn.answer.citations.length && <div className="answer-sources"><span className="eyebrow">SOURCES · {turn.answer.citations.length}</span>{turn.answer.citations.map(source => <button className="source-card" key={source.id} onClick={() => openCitation(source)}><span className="source-number">{source.id}</span><span className="source-card-content"><strong>{source.section_path.at(-1)}</strong><span>PDF p. {source.pdf_page}{source.printed_page ? ` · Printed p. ${source.printed_page}` : ''}</span></span><ChevronRight size={15} /></button>)}</div>}
            </div>}
            {turn.error && <div className="message-error" role="alert"><CircleHelp size={19} /><div><strong>We couldn’t complete that answer.</strong><p>{turn.error}</p>{turn.requestId && <small>Request {turn.requestId}</small>}<button className="text-button" disabled={busy} onClick={() => void submit(turn.query, turn.id)}><RefreshCw size={13} /> Try again</button></div></div>}
          </article>)}
          {busy && <div className="answer-loading" role="status"><span className="small-logo"><LoaderCircle size={16} className="spin" /></span><div><strong>Working through the filing</strong><span>Finding relevant passages and verifying the answer.</span></div><span className="loading-dots"><i /><i /><i /></span></div>}
          <div ref={endRef} />
        </div>

        <div className="composer-area">
          {(connectionError || (health && !ready)) && <details className="setup-notice"><summary><span className="status-dot amber" />{connectionError ? 'Backend connection unavailable' : 'Connect OpenAI to start asking'}<ChevronRight size={14} /></summary><div>{connectionError ? <p>{connectionError}</p> : <><p>The filing is available to read. To enable answers:</p><ol><li>Add your API key to <code>OPENAI_API_KEY</code> in the local <code>.env</code> file.</li><li>Run <code>python -m app.ingest</code> in the project environment.</li><li>Restart the backend and check the connection below.</li></ol></>}<button className="text-button" onClick={() => void refresh()} disabled={checking}><RefreshCw size={13} className={checking ? 'spin' : ''} /> Check connection</button></div></details>}
          <form className={`composer ${busy ? 'is-busy' : ''}`} onSubmit={onSubmit}>
            <label className="sr-only" htmlFor="question">Ask a question about the filing</label>
            <textarea id="question" ref={textarea} value={query} maxLength={2000} placeholder="Ask a question about the filing…" rows={2} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(query) } }} />
            <div className="composer-bottom"><span><FileText size={13} /> Apple 2023 10-K</span><div><span className="character-count">{query.length ? `${query.length} / 2,000` : 'Enter to send'}</span><button className="send-button" type="submit" aria-label="Send question" disabled={!query.trim() || busy}>{busy ? <LoaderCircle size={18} className="spin" /> : <ArrowUp size={19} />}</button></div></div>
          </form>
          <div className="composer-footnote"><span>Each question is answered independently.</span><span><span className={`status-dot ${ready ? 'green' : 'amber'}`} />{health?.model ?? 'gpt-6-luna'}</span></div>
        </div>
      </main>

      {sourceOpen && <button className="panel-backdrop" aria-label="Close source panel" onClick={closeSource} />}
      <aside ref={asideRef} tabIndex={-1} className={`source-panel ${sourceOpen ? 'is-open' : ''}`} aria-label="Document and sources" onKeyDown={onPanelKey}>
        <div className="source-panel-header"><span><BookOpen size={16} />{citation ? 'Source detail' : 'Source document'}</span><button className="icon-button close-source" aria-label="Close source panel" onClick={closeSource}><X size={17} /></button>{viewerOpen && <button className="text-button back-to-document" onClick={() => { setViewerOpen(false); setCitation(null) }}>Overview</button>}</div>
        {!viewerOpen ? <div className="document-overview">
          <div className="filing-cover"><div className="cover-top"><span>ANNUAL REPORT</span><span>01 / 80</span></div><div className="cover-company">Apple Inc.</div><div className="cover-year">2023</div><div className="cover-bottom"><span>FORM 10-K</span><FileText size={23} strokeWidth={1} /></div></div>
          <h2>Apple’s year,<br />in its own words.</h2><p className="document-caption">The annual filing for the fiscal year ended September 30, 2023.</p>
          <div className="document-metadata"><div><span>DOCUMENT</span><strong>Form 10-K</strong></div><div><span>LENGTH</span><strong>{documentInfo?.page_count ?? 80} pages</strong></div><div><span>PERIOD</span><strong>FY 2023</strong></div></div>
          <button className="read-button" onClick={() => browse()}><BookOpen size={16} /> Read the filing <ArrowRight size={16} /></button>
          <div className="document-outline"><span className="eyebrow">IN THIS FILING</span>{[{ part: 'I', title: 'Business & risk factors', page: 4 }, { part: 'II', title: 'Performance & financial statements', page: 21 }, { part: 'III', title: 'Governance & compensation', page: 56 }, { part: 'IV', title: 'Exhibits & schedules', page: 57 }].map(section => <button key={section.part} onClick={() => browse(section.page)}><span className="part-number">{section.part}</span><span>{section.title}</span><ChevronRight size={14} /></button>)}</div>
          <div className="source-hint"><Search size={17} /><p>Follow any citation to see the supporting passage in the original document.</p></div>
        </div> : <>
          {citation && <div className="citation-detail"><div className="citation-kicker"><span className="source-number">{citation.id}</span> SUPPORTING PASSAGE</div><nav className="section-breadcrumb" aria-label="Source section">{citation.section_path.slice(0, -1).map((section, i) => <span key={i}>{section}<ChevronRight size={11} /></span>)}</nav><h2>{citation.section_path.at(-1)}</h2><div className="page-label"><FileText size={13} /> PDF page {citation.pdf_page}{citation.printed_page && <><span>·</span>Printed page {citation.printed_page}</>}</div><button className="excerpt-toggle" aria-expanded={showExcerpt} onClick={() => setShowExcerpt(value => !value)}>{showExcerpt ? <Check size={13} /> : <ArrowDown size={13} />}{showExcerpt ? 'Hide text excerpt' : 'Show text excerpt'}</button>{showExcerpt && <pre className="source-excerpt">{citation.excerpt}</pre>}</div>}
          <Suspense fallback={<div className="pdf-loading"><LoaderCircle size={18} className="spin" /> Loading viewer</div>}><PdfViewer page={viewerPage} rectangles={highlights} onPageChange={setViewerPage} /></Suspense>
        </>}
      </aside>
    </div>
  </div>
}

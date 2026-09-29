import { useEffect, useRef, useState } from 'react'
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { ChevronLeft, ChevronRight, ExternalLink, LoaderCircle } from 'lucide-react'
import type { Rect } from './types'

GlobalWorkerOptions.workerSrc = workerUrl

export default function PdfViewer({ page, rectangles, onPageChange }: {
  page: number; rectangles: Rect[]; onPageChange: (page: number) => void
}) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [width, setWidth] = useState(400)
  const [pageInput, setPageInput] = useState(String(page))
  const hostRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const rendering = useRef<RenderTask | null>(null)

  useEffect(() => {
    const task = getDocument({ url: '/api/document/pdf' })
    let cancelled = false
    task.promise.then(document => { if (!cancelled) setPdf(document) })
      .catch(() => { if (!cancelled) { setError('The PDF could not be loaded. Open the original file below.'); setLoading(false) } })
    return () => { cancelled = true; void task.destroy() }
  }, [])

  useEffect(() => {
    if (!hostRef.current) return
    const observer = new ResizeObserver(entries => setWidth(Math.max(180, entries[0].contentRect.width - 32)))
    observer.observe(hostRef.current)
    return () => observer.disconnect()
  }, [])

  useEffect(() => { setPageInput(String(page)) }, [page])

  useEffect(() => {
    if (!pdf || !canvasRef.current) return
    let cancelled = false
    rendering.current?.cancel()
    const previous = rendering.current?.promise.catch(() => {})
    const render = async () => {
      await previous
      if (cancelled) return
      setLoading(true)
      setError('')
      try {
        const pdfPage = await pdf.getPage(page)
        if (cancelled || !canvasRef.current) return
        const viewport = pdfPage.getViewport({ scale: width / pdfPage.getViewport({ scale: 1 }).width })
        const canvas = canvasRef.current
        const ratio = window.devicePixelRatio || 1
        canvas.width = Math.floor(viewport.width * ratio)
        canvas.height = Math.floor(viewport.height * ratio)
        setSize({ width: viewport.width, height: viewport.height })
        const task = pdfPage.render({ canvas, viewport, transform: [ratio, 0, 0, ratio, 0, 0] })
        rendering.current = task
        await task.promise
        if (!cancelled) {
          setLoading(false)
          if (scrollRef.current) scrollRef.current.scrollTop = rectangles.length ? Math.max(0, rectangles[0].y * viewport.height - 60) : 0
        }
      } catch (err) {
        if (!cancelled && !(err instanceof Error && err.name === 'RenderingCancelledException')) {
          setError('This page could not be rendered. Open the original PDF below.')
          setLoading(false)
        }
      }
    }
    void render()
    return () => { cancelled = true; rendering.current?.cancel() }
  }, [pdf, page, width, rectangles])

  function jump() {
    const next = Number(pageInput)
    if (Number.isInteger(next) && next >= 1 && next <= (pdf?.numPages ?? 80)) onPageChange(next)
    else setPageInput(String(page))
  }

  return <div className="pdf-viewer" ref={hostRef}>
    <div className="pdf-toolbar">
      <span>ORIGINAL FILING</span>
      <div className="page-controls">
        <button className="icon-button" aria-label="Previous PDF page" disabled={page <= 1} onClick={() => onPageChange(page - 1)}><ChevronLeft size={16} /></button>
        <label><span className="sr-only">PDF page</span><input value={pageInput} inputMode="numeric" aria-label="PDF page" onChange={event => setPageInput(event.target.value)} onBlur={jump} onKeyDown={event => { if (event.key === 'Enter') jump() }} /></label>
        <span>/ {pdf?.numPages ?? 80}</span>
        <button className="icon-button" aria-label="Next PDF page" disabled={page >= (pdf?.numPages ?? 80)} onClick={() => onPageChange(page + 1)}><ChevronRight size={16} /></button>
      </div>
    </div>
    <div className="pdf-scroll" ref={scrollRef}>
      {error && <div className="pdf-error" role="alert">{error}</div>}
      {loading && <div className="pdf-loading"><LoaderCircle size={18} className="spin" /> Loading page</div>}
      <div className="pdf-page" style={{ width: size.width || width, height: size.height || 520, visibility: error ? 'hidden' : 'visible' }}>
        <canvas ref={canvasRef} style={{ width: size.width, height: size.height }} aria-label={`PDF page ${page}. Supporting text is provided in the source excerpt above.`} />
        {!loading && rectangles.map((rect, i) => <div key={i} className="pdf-highlight" style={{ left: `${rect.x * 100}%`, top: `${rect.y * 100}%`, width: `${rect.width * 100}%`, height: `${rect.height * 100}%` }} />)}
      </div>
    </div>
    <a className="pdf-original" href={`/api/document/pdf#page=${page}`} target="_blank" rel="noreferrer">Open original PDF <ExternalLink size={13} /></a>
  </div>
}

export type Rect = { x: number; y: number; width: number; height: number }
export type Citation = {
  id: string
  document_id: string
  pdf_page: number
  printed_page: string | null
  section_path: string[]
  excerpt: string
  highlight_rects: Rect[]
}
export type Answer = {
  status: 'answered' | 'partial' | 'insufficient_evidence' | 'needs_clarification'
  answer_blocks: { text: string; citation_ids: string[] }[]
  citations: Citation[]
  request_id: string
}
export type Health = {
  status: 'ready' | 'setup_required'
  index_status: string
  api_key_configured: boolean
  model: string
  passage_count: number
}
export type DocumentInfo = { id: string; title: string; filename: string; page_count: number; pdf_url: string }
export type Turn = { id: string; query: string; answer?: Answer; error?: string; requestId?: string }

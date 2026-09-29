import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { Answer } from './types'

vi.mock('./PdfViewer', () => ({ default: ({ page, rectangles }: { page: number; rectangles: unknown[] }) => <div data-testid="pdf-viewer">Page {page}, {rectangles.length} highlights</div> }))

const answer: Answer = {
  status: 'answered', request_id: 'test-request',
  answer_blocks: [{ text: 'Total net sales were $383,285 million in 2023.', citation_ids: ['1'] }],
  citations: [{ id: '1', document_id: 'document', pdf_page: 31, printed_page: '28',
    section_path: ['PART II', 'Item 8. Financial Statements and Supplementary Data', 'CONSOLIDATED STATEMENTS OF OPERATIONS'],
    excerpt: 'Total net sales 383,285 394,328 365,817',
    highlight_rects: [{ x: .1, y: .2, width: .8, height: .02 }] }],
}

function response(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
}

let fetcher: ReturnType<typeof vi.fn<(url: string) => Promise<Response>>>
beforeEach(() => {
  fetcher = vi.fn(async (url: string) => {
    if (url === '/api/health') return response({ status: 'ready', index_status: 'ready', api_key_configured: true, model: 'gpt-6-luna', passage_count: 300 })
    if (url === '/api/document') return response({ id: 'document', title: 'Apple 2023', filename: 'filing.pdf', page_count: 80, pdf_url: '/api/document/pdf' })
    return response(answer)
  })
  vi.stubGlobal('fetch', fetcher)
})

describe('filing chat', () => {
  it('submits only the query and opens a cited page with its section and highlight', async () => {
    render(<App />)
    const input = screen.getByLabelText('Ask a question about the filing')
    fireEvent.change(input, { target: { value: 'What were total net sales in 2023?' } })
    fireEvent.click(screen.getByLabelText('Send question'))
    expect(await screen.findByText('Total net sales were $383,285 million in 2023.')).toBeInTheDocument()
    const call = fetcher.mock.calls.find(args => args[0] === '/api/chat') as unknown as [string, RequestInit]
    expect(JSON.parse(call[1].body as string)).toEqual({ query: 'What were total net sales in 2023?' })
    fireEvent.click(screen.getByLabelText('View source 1, PDF page 31'))
    expect(await screen.findByTestId('pdf-viewer')).toHaveTextContent('Page 31, 1 highlights')
    expect(screen.getByRole('heading', { name: 'CONSOLIDATED STATEMENTS OF OPERATIONS' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show text excerpt' }))
    expect(screen.getByText('Total net sales 383,285 394,328 365,817')).toBeInTheDocument()
  })

  it('keeps a failed question retryable without creating a duplicate turn', async () => {
    let chatCalls = 0
    const implementation = fetcher.getMockImplementation()!
    fetcher.mockImplementation(async (url: string) => {
      if (url === '/api/chat' && ++chatCalls === 1) return response({ error: { message: 'Connection lost' }, request_id: 'failed-request' }, 503)
      return implementation(url)
    })
    render(<App />)
    fireEvent.change(screen.getByLabelText('Ask a question about the filing'), { target: { value: 'Net sales?' } })
    fireEvent.click(screen.getByLabelText('Send question'))
    expect(await screen.findByText('Connection lost')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Total net sales were $383,285 million in 2023.')).toBeInTheDocument()
    expect(screen.getAllByText('Net sales?')).toHaveLength(1)
  })

  it('can browse the source without an API key and explains setup', async () => {
    const implementation = fetcher.getMockImplementation()!
    fetcher.mockImplementation(async (url: string) => url === '/api/health'
      ? response({ status: 'setup_required', api_key_configured: false, index_status: 'text_only', model: 'gpt-6-luna' })
      : implementation(url))
    render(<App />)
    expect(await screen.findByText('Connect OpenAI to start asking')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Read the filing' }))
    expect(screen.getByTestId('pdf-viewer')).toHaveTextContent('Page 1')
  })

  it('prevents empty submissions and sends Enter as a standalone question', async () => {
    render(<App />)
    expect(screen.getByLabelText('Send question')).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Ask a question about the filing'), { target: { value: 'What were sales?' } })
    fireEvent.keyDown(screen.getByLabelText('Ask a question about the filing'), { key: 'Enter' })
    await waitFor(() => expect(fetcher.mock.calls.some(args => args[0] === '/api/chat')).toBe(true))
  })
})

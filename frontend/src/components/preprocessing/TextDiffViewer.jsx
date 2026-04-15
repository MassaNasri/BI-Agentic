import { useMemo } from 'react'

const splitWords = (text) =>
  String(text || '')
    .trim()
    .split(/\s+/)
    .filter(Boolean)

const buildDiffSegments = (beforeText, afterText) => {
  const beforeWords = splitWords(beforeText)
  const afterWords = splitWords(afterText)

  const n = beforeWords.length
  const m = afterWords.length
  const matrix = Array.from({ length: n + 1 }, () => Array(m + 1).fill(0))

  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      if (beforeWords[i].toLowerCase() === afterWords[j].toLowerCase()) {
        matrix[i][j] = matrix[i + 1][j + 1] + 1
      } else {
        matrix[i][j] = Math.max(matrix[i + 1][j], matrix[i][j + 1])
      }
    }
  }

  const operations = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (beforeWords[i].toLowerCase() === afterWords[j].toLowerCase()) {
      operations.push({ type: 'equal', word: beforeWords[i] })
      i += 1
      j += 1
      continue
    }

    if (matrix[i + 1][j] >= matrix[i][j + 1]) {
      operations.push({ type: 'removed', word: beforeWords[i] })
      i += 1
    } else {
      operations.push({ type: 'added', word: afterWords[j] })
      j += 1
    }
  }

  while (i < n) {
    operations.push({ type: 'removed', word: beforeWords[i] })
    i += 1
  }

  while (j < m) {
    operations.push({ type: 'added', word: afterWords[j] })
    j += 1
  }

  const compact = []
  for (const operation of operations) {
    const prev = compact[compact.length - 1]
    if (prev && prev.type === operation.type) {
      prev.words.push(operation.word)
      continue
    }
    compact.push({ type: operation.type, words: [operation.word] })
  }

  return compact.map((segment) => ({
    type: segment.type,
    text: segment.words.join(' '),
  }))
}

const segmentClassName = (segmentType, mode) => {
  if (segmentType === 'equal') {
    return 'text-slate-700 dark:text-slate-200'
  }
  if (mode === 'original' && segmentType === 'removed') {
    return 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-200 line-through'
  }
  if (mode === 'cleaned' && segmentType === 'added') {
    return 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200'
  }
  return 'text-slate-400 dark:text-slate-500'
}

function DiffLine({ label, mode, segments }) {
  const filtered = segments.filter((segment) => {
    if (segment.type === 'equal') return true
    if (mode === 'original') return segment.type !== 'added'
    return segment.type !== 'removed'
  })

  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm leading-6 dark:border-slate-700 dark:bg-slate-900/40">
        {filtered.length === 0 ? (
          <span className="text-slate-400 dark:text-slate-500">No content</span>
        ) : (
          filtered.map((segment, index) => (
            <span
              key={`${segment.type}-${index}`}
              className={`mr-1 inline-block rounded px-1 py-0.5 ${segmentClassName(segment.type, mode)}`}
            >
              {segment.text}
            </span>
          ))
        )}
      </div>
    </div>
  )
}

function TextDiffViewer({ originalText, cleanedText }) {
  const segments = useMemo(
    () => buildDiffSegments(originalText, cleanedText),
    [originalText, cleanedText]
  )

  return (
    <div className="space-y-4">
      <DiffLine label="Original Sentence" mode="original" segments={segments} />
      <DiffLine label="Cleaned Sentence" mode="cleaned" segments={segments} />
    </div>
  )
}

export default TextDiffViewer

import { useState } from 'react'

const DEFAULT_API = import.meta.env.VITE_METADATA_API_URL || 'http://localhost:8006/api'

function LineageExplorer() {
  const [rowId, setRowId] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  const fetchLineage = async () => {
    setError('')
    setResult(null)
    if (!rowId) {
      setError('Row ID is required')
      return
    }
    try {
      const res = await fetch(`${DEFAULT_API}/lineage/${rowId}/`)
      const data = await res.json()
      if (!data?.success) {
        setError(data?.message || 'Failed to fetch lineage')
        return
      }
      setResult(data?.data || data)
    } catch (err) {
      setError('Failed to fetch lineage')
    }
  }

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-semibold">Lineage Explorer</h1>
      <div className="flex gap-2">
        <input
          className="border rounded px-3 py-2 w-full"
          placeholder="Enter lineage row_id (UUID)"
          value={rowId}
          onChange={(e) => setRowId(e.target.value)}
        />
        <button
          className="bg-black text-white px-4 py-2 rounded"
          onClick={fetchLineage}
        >
          Fetch
        </button>
      </div>
      {error && <div className="text-red-600">{error}</div>}
      {result && (
        <pre className="bg-gray-100 p-4 rounded text-sm overflow-auto">
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
    </div>
  )
}

export default LineageExplorer

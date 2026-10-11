import { useCallback, useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  Upload, Database as DatabaseIcon, FileText, Trash2, 
  AlertCircle, CheckCircle, Loader, Info, Table, 
  AlertTriangle, Server, PlugZap
} from 'lucide-react'
import { databaseAPI } from '../../api/endpoints'
import toast from 'react-hot-toast'
import { fadeIn, cardVariants, scaleIn } from '../../animations/variants'
import { Card, Button, Modal, LoadingSpinner } from '../../components'
import {
  buildInitialConfiguration,
  connectorWorkflow,
  isSupportedLegacyUpload,
  pollOutcome,
  redactTransientSecrets,
  sourceErrorMessage,
  tableSelectionKey,
} from './databaseSourceState'

function DatabaseManagement() {
  const [database, setDatabase] = useState(null)
  const [previewData, setPreviewData] = useState(null)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [isDragging, setIsDragging] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showReplaceModal, setShowReplaceModal] = useState(false)
  const [fileToUpload, setFileToUpload] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isLoadingPreview, setIsLoadingPreview] = useState(false)
  const [sourceMode, setSourceMode] = useState('file')
  const [selectedTableId, setSelectedTableId] = useState(null)

  const loadPreview = useCallback(async (tableId = null) => {
    try {
      setIsLoadingPreview(true)
      const response = await databaseAPI.getDatabasePreview(tableId)
      if (response.data.success) {
        setPreviewData(response.data.data)
      }
    } catch (error) {
      console.error('Error loading preview:', error)
    } finally {
      setIsLoadingPreview(false)
    }
  }, [])

  const loadDatabaseInfo = useCallback(async () => {
    try {
      setIsLoading(true)
      const response = await databaseAPI.getDatabaseInfo()
      if (response.data.success) {
        setDatabase(response.data.data)
        // Load preview if database is completed
        if (response.data.data.etl_status === 'completed') {
          const firstTableId = response.data.data.source_tables?.[0]?.id || null
          setSelectedTableId(firstTableId)
          loadPreview(firstTableId)
        }
      }
    } catch (error) {
      if (
        error.response?.status === 404 ||
        error.response?.data?.code === 'dataset_metadata_missing'
      ) {
        // No database found - this is normal for new users
        setDatabase(null)
      } else if (error.response?.status === 503) {
        console.error('Backend service unavailable:', error)
        // Don't show error for initial load - user hasn't uploaded yet
        setDatabase(null)
      } else {
        console.error('Error loading database:', error)
        // Only show error if it's not a connection issue on first load
        if (error.response) {
          toast.error('Failed to load database information')
        }
      }
    } finally {
      setIsLoading(false)
    }
  }, [loadPreview])

  useEffect(() => {
    loadDatabaseInfo()
  }, [loadDatabaseInfo])

  useEffect(() => {
    if (database?.etl_status !== 'processing') return undefined

    let cancelled = false
    let consecutiveErrors = 0
    let intervalId

    const checkStatus = async () => {
      try {
        const response = await databaseAPI.getDatabaseInfo()
        if (cancelled || !response.data.success) return
        consecutiveErrors = 0
        const db = response.data.data
        setDatabase(db)

        const outcome = pollOutcome(db.etl_status)
        if (outcome.stop && intervalId) clearInterval(intervalId)
        if (outcome.loadPreview) {
          toast.success('Database processing completed!')
          const firstTableId = db.source_tables?.[0]?.id || null
          setSelectedTableId(firstTableId)
          loadPreview(firstTableId)
        } else if (outcome.failed) {
          toast.error(db.etl_message || 'Database processing failed')
        }
      } catch (error) {
        consecutiveErrors += 1
        console.error('ETL status check failed:', error)
        if (consecutiveErrors === 5) {
          toast.error('Status checks are temporarily unavailable. Retrying automatically…')
        }
      }
    }

    checkStatus()
    intervalId = setInterval(checkStatus, 3000)
    return () => {
      cancelled = true
      if (intervalId) clearInterval(intervalId)
    }
  }, [database?.etl_status, loadPreview])

  const handleFileSelect = (file) => {
    if (!file) return
    
    if (!isSupportedLegacyUpload(file)) {
      toast.error('Please upload a valid CSV or Excel file')
      return
    }

    // Check if database exists (replace mode)
    if (database) {
      setFileToUpload(file)
      setShowReplaceModal(true)
    } else {
      uploadFile(file)
    }
  }

  const uploadFile = async (file) => {
    try {
      setIsUploading(true)
      setUploadProgress(0)

      const response = await databaseAPI.uploadDatabase(file, (progressEvent) => {
        const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total)
        setUploadProgress(percentCompleted)
      })

      if (response.data.success) {
        toast.success(response.data.message)
        setDatabase(response.data.data)
        setShowReplaceModal(false)
        setFileToUpload(null)
        
      }
    } catch (error) {
      console.error('Upload error:', error)
      
      // Defensive error message handling
      let errorMessage = 'Upload failed'
      
      if (error.response) {
        // Server responded with error
        const status = error.response.status
        const data = error.response.data
        
        if (status === 503) {
          errorMessage = 'ETL service is unavailable. Please ensure the ETL system is running and try again.'
        } else if (status === 504) {
          errorMessage = 'Upload timeout. Please try again with a smaller file.'
        } else if (status === 502) {
          errorMessage = 'ETL service error. Please check the ETL system logs.'
        } else if (status === 404) {
          errorMessage = 'Database upload endpoint not found. Please contact support.'
        } else if (data && typeof data === 'object' && data.message) {
          errorMessage = data.message
        } else if (typeof data === 'string') {
          errorMessage = data
        }
      } else if (error.request) {
        // Request made but no response
        errorMessage = 'Cannot connect to backend. Please ensure the server is running.'
      } else {
        // Something else happened
        errorMessage = error.message || 'An unexpected error occurred'
      }
      
      toast.error(errorMessage)
    } finally {
      setIsUploading(false)
      setUploadProgress(0)
    }
  }

  const handleDelete = async () => {
    try {
      const response = await databaseAPI.deleteDatabase()
      if (response.data.success) {
        toast.success('Database deleted successfully')
        setDatabase(null)
        setPreviewData(null)
        setSelectedTableId(null)
        setShowDeleteModal(false)
      }
    } catch (error) {
      console.error('Delete error:', error)
      
      // Defensive error handling
      let errorMessage = 'Delete failed'
      if (error.response?.data?.message) {
        errorMessage = error.response.data.message
      } else if (error.response?.status === 404) {
        errorMessage = 'Database not found'
        // Still reset UI since it doesn't exist
        setDatabase(null)
        setPreviewData(null)
        setSelectedTableId(null)
        setShowDeleteModal(false)
      } else if (!error.response) {
        errorMessage = 'Cannot connect to backend'
      }
      
      toast.error(errorMessage)
    }
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = (e) => {
    e.preventDefault()
    setIsDragging(false)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setIsDragging(false)
    
    const files = e.dataTransfer.files
    if (files.length > 0) {
      handleFileSelect(files[0])
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <LoadingSpinner size="large" />
      </div>
    )
  }

  return (
    <motion.div
      variants={fadeIn}
      initial="hidden"
      animate="visible"
      className="max-w-7xl mx-auto space-y-6"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">Database Management</h1>
          <p className="mt-2 text-[var(--c-muted)]">Upload and manage your data source</p>
        </div>
        {database && (
          <Button
            variant="danger"
            icon={Trash2}
            onClick={() => setShowDeleteModal(true)}
          >
            Delete Database
          </Button>
        )}
      </div>

      {/* Upload Area or Database Info */}
      {!database ? (
        <motion.div variants={cardVariants} initial="hidden" animate="visible">
          <div className="space-y-4">
            <div className="flex gap-2" role="tablist" aria-label="Data source type">
              <Button variant={sourceMode === 'file' ? 'primary' : 'secondary'} icon={FileText} onClick={() => setSourceMode('file')}>
                File source
              </Button>
              <Button variant={sourceMode === 'database' ? 'primary' : 'secondary'} icon={Server} onClick={() => setSourceMode('database')}>
                Database source
              </Button>
            </div>
            {sourceMode === 'file' ? (
              <UploadArea
                isDragging={isDragging}
                isUploading={isUploading}
                uploadProgress={uploadProgress}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onFileSelect={handleFileSelect}
              />
            ) : (
              <DatabaseSourcePanel
                onStarted={(data) => {
                  setDatabase(data)
                }}
              />
            )}
          </div>
        </motion.div>
      ) : (
        <>
          <motion.div variants={cardVariants} initial="hidden" animate="visible">
            <DatabaseInfo database={database} />
          </motion.div>
          
          {database.etl_status === 'completed' && previewData && (
            <>
              {database.source_kind === 'database' && database.source_tables?.length > 0 && (
                <ImportedTableSelector
                  tables={database.source_tables}
                  selectedTableId={selectedTableId || database.source_tables[0]?.id}
                  disabled={isLoadingPreview}
                  onSelect={(tableId) => {
                    setSelectedTableId(tableId)
                    loadPreview(tableId)
                  }}
                />
              )}
              <motion.div variants={cardVariants} initial="hidden" animate="visible" transition={{ delay: 0.1 }}>
                <SchemaPreview schema={previewData} />
              </motion.div>
              <motion.div variants={cardVariants} initial="hidden" animate="visible" transition={{ delay: 0.2 }}>
                <DataPreview previewData={previewData} isLoading={isLoadingPreview} />
              </motion.div>
            </>
          )}
          
          {database.etl_status === 'processing' && (
            <motion.div variants={cardVariants} initial="hidden" animate="visible">
              <ProcessingCard />
            </motion.div>
          )}
          
          {database.etl_status === 'failed' && (
            <motion.div variants={cardVariants} initial="hidden" animate="visible">
              <ErrorCard message={database.etl_message} />
            </motion.div>
          )}
        </>
      )}

      {/* Replace Database Modal */}
      <AnimatePresence>
        {showReplaceModal && (
          <Modal
            isOpen={showReplaceModal}
            onClose={() => {
              setShowReplaceModal(false)
              setFileToUpload(null)
            }}
            title="Replace Database"
          >
            <div className="space-y-4">
              <div className="flex items-start space-x-3 p-4 bg-amber-500/15 border border-amber-500/30 rounded-lg">
                <AlertTriangle className="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="font-semibold text-amber-400">Warning: This action cannot be undone</p>
                  <p className="text-sm text-amber-400 mt-1">
                    This will permanently delete your current database and all data stored in ClickHouse.
                    The new file will be uploaded and processed automatically.
                  </p>
                </div>
              </div>
              
              <div className="space-y-2">
                <p className="text-sm text-[var(--c-muted)]">
                  <strong>Current file:</strong> {database?.filename}
                </p>
                <p className="text-sm text-[var(--c-muted)]">
                  <strong>New file:</strong> {fileToUpload?.name}
                </p>
              </div>

              <div className="flex space-x-3">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setShowReplaceModal(false)
                    setFileToUpload(null)
                  }}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  onClick={() => uploadFile(fileToUpload)}
                  disabled={isUploading}
                  className="flex-1"
                >
                  {isUploading ? 'Replacing...' : 'Replace Database'}
                </Button>
              </div>
            </div>
          </Modal>
        )}
      </AnimatePresence>

      {/* Delete Confirmation Modal */}
      <AnimatePresence>
        {showDeleteModal && (
          <Modal
            isOpen={showDeleteModal}
            onClose={() => setShowDeleteModal(false)}
            title="Delete Database"
          >
            <div className="space-y-4">
              <div className="flex items-start space-x-3 p-4 bg-red-50 border border-red-200 rounded-lg">
                <AlertTriangle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="font-semibold text-red-900">Warning: This action cannot be undone</p>
                  <p className="text-sm text-red-700 mt-1">
                    This will permanently delete your database and all associated data from ClickHouse.
                  </p>
                </div>
              </div>

              <div className="flex space-x-3">
                <Button
                  variant="secondary"
                  onClick={() => setShowDeleteModal(false)}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  onClick={handleDelete}
                  className="flex-1"
                >
                  Delete Permanently
                </Button>
              </div>
            </div>
          </Modal>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

function DatabaseSourcePanel({ onStarted }) {
  const [connectors, setConnectors] = useState([])
  const [engine, setEngine] = useState('')
  const [configuration, setConfiguration] = useState({})
  const [schemas, setSchemas] = useState([])
  const [schema, setSchema] = useState('')
  const [tables, setTables] = useState([])
  const [selectedTables, setSelectedTables] = useState([])
  const [state, setState] = useState('idle')
  const [message, setMessage] = useState('')

  const connector = connectors.find((item) => item.id === engine)

  useEffect(() => {
    let active = true
    databaseAPI.getSourceCapabilities()
      .then((response) => {
        if (!active) return
        const available = response.data?.data?.connectors || []
        setConnectors(available)
        if (available.length) setEngine(available[0].id)
      })
      .catch(() => setMessage('Could not load database connector capabilities.'))
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!connector) return
    setConfiguration(buildInitialConfiguration(connector))
    setSchemas([])
    setSchema('')
    setTables([])
    setSelectedTables([])
    setState('idle')
    setMessage('')
  }, [connector])

  const setField = (name, value) => setConfiguration((current) => ({ ...current, [name]: value }))
  const testConnection = async () => {
    setState('testing')
    setMessage('')
    try {
      await databaseAPI.testSourceConnection(engine, configuration)
      setState('test-success')
      setMessage('Connection successful. You can now discover tables.')
    } catch (error) {
      setState('failed')
      setMessage(sourceErrorMessage(error, 'Connection test failed.'))
    }
  }

  const discover = async (selectedSchema = schema) => {
    setState('discovering')
    setMessage('')
    try {
      const response = await databaseAPI.discoverSource(engine, configuration, selectedSchema || null)
      const data = response.data?.data || {}
      setSchemas(data.schemas || [])
      setTables(data.tables || [])
      setSelectedTables([])
      setState('ready')
      setMessage(data.tables?.length ? 'Select the tables to import.' : 'No tables are available for this connection.')
    } catch (error) {
      setState('failed')
      setMessage(sourceErrorMessage(error, 'Table discovery failed.'))
    }
  }

  const prepareSQLite = async (file) => {
    if (!file) return
    setState('testing')
    setMessage('Uploading and validating the SQLite database…')
    try {
      const response = await databaseAPI.prepareSQLite(file)
      const data = response.data?.data || {}
      setConfiguration({ sqlite_token: data.sqlite_token })
      setTables(data.tables || [])
      setSelectedTables([])
      setState('ready')
      setMessage('SQLite database validated. Select the tables to import.')
    } catch (error) {
      setState('failed')
      setMessage(sourceErrorMessage(error, 'SQLite validation failed.'))
    }
  }

  const toggleTable = (table) => {
    const key = tableSelectionKey(table)
    setSelectedTables((current) => current.some((item) => tableSelectionKey(item) === key)
      ? current.filter((item) => tableSelectionKey(item) !== key)
      : [...current, { schema: table.schema || null, name: table.name }])
  }

  const startSnapshot = async () => {
    setState('starting')
    setMessage('Starting snapshot ingestion…')
    try {
      const response = await databaseAPI.startSnapshot(engine, configuration, selectedTables)
      setConfiguration((current) => redactTransientSecrets(current))
      setState('started')
      setMessage('Snapshot extraction started.')
      onStarted(response.data.data)
    } catch (error) {
      setState('failed')
      setMessage(sourceErrorMessage(error, 'Snapshot could not be started.'))
    }
  }

  const busy = ['testing', 'discovering', 'starting'].includes(state)

  return (
    <Card className="p-6 space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-white flex items-center gap-2"><DatabaseIcon className="w-5 h-5" /> Database snapshot</h2>
        <p className="text-sm text-[var(--c-muted)] mt-1">Connect securely, inspect metadata, and run a one-time import. Continuous synchronization is not enabled.</p>
      </div>

      <label className="block text-sm text-[var(--c-muted)]">
        Database engine
        <select
          value={engine}
          onChange={(event) => setEngine(event.target.value)}
          disabled={busy}
          className="mt-1 w-full rounded-lg border border-brand-700/50 bg-[var(--c-surface)] p-3 text-white"
        >
          {connectors.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
      </label>

      {connectorWorkflow(connector) === 'sqlite-upload' ? (
        <label className="block rounded-lg border border-dashed border-brand-600/50 p-5 text-center text-sm text-[var(--c-muted)] cursor-pointer">
          Upload a server-readable SQLite file
          <input type="file" accept=".db,.sqlite,.sqlite3" className="hidden" onChange={(event) => prepareSQLite(event.target.files?.[0])} disabled={busy} />
        </label>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {connector?.fields.filter((field) => field.type !== 'file').map((field) => (
            <label key={field.name} className="text-sm text-[var(--c-muted)]">
              {field.label}{field.required ? ' *' : ''}
              {field.type === 'select' ? (
                <select value={configuration[field.name] ?? ''} onChange={(event) => setField(field.name, event.target.value)} disabled={busy} className="mt-1 w-full rounded-lg border border-brand-700/50 bg-[var(--c-surface)] p-3 text-white">
                  {(field.options || []).map((option) => <option key={option} value={option}>{option}</option>)}
                </select>
              ) : field.type === 'boolean' ? (
                <input type="checkbox" checked={Boolean(configuration[field.name])} onChange={(event) => setField(field.name, event.target.checked)} disabled={busy} className="ml-3" />
              ) : (
                <input
                  type={field.type === 'password' ? 'password' : field.type === 'number' ? 'number' : 'text'}
                  value={configuration[field.name] ?? ''}
                  onChange={(event) => setField(field.name, field.type === 'number' ? Number(event.target.value) : event.target.value)}
                  required={field.required}
                  autoComplete={field.type === 'password' ? 'new-password' : 'off'}
                  disabled={busy}
                  className="mt-1 w-full rounded-lg border border-brand-700/50 bg-[var(--c-surface)] p-3 text-white"
                />
              )}
            </label>
          ))}
        </div>
      )}

      {connectorWorkflow(connector) !== 'sqlite-upload' && (
        <div className="flex flex-wrap gap-3">
          <Button icon={PlugZap} onClick={testConnection} disabled={busy}>Test connection</Button>
          <Button variant="secondary" icon={Table} onClick={() => discover()} disabled={busy || state !== 'test-success'}>Discover tables</Button>
        </div>
      )}

      {schemas.length > 0 && (
        <label className="block text-sm text-[var(--c-muted)]">
          Schema
          <select value={schema} onChange={(event) => { setSchema(event.target.value); discover(event.target.value) }} disabled={busy} className="mt-1 w-full rounded-lg border border-brand-700/50 bg-[var(--c-surface)] p-3 text-white">
            <option value="">All available schemas</option>
            {schemas.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
      )}

      {tables.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm font-medium text-white">Tables and views</p>
          <div className="max-h-56 overflow-auto rounded-lg border border-brand-700/40 divide-y divide-brand-700/30">
            {tables.map((table) => {
              const key = tableSelectionKey(table)
              const checked = selectedTables.some((item) => tableSelectionKey(item) === key)
              return (
                <label key={key} className="flex items-center gap-3 p-3 text-sm text-white hover:bg-white/5">
                  <input type="checkbox" checked={checked} onChange={() => toggleTable(table)} disabled={busy} />
                  <span>{table.schema ? `${table.schema}.` : ''}{table.name}</span>
                  <span className="ml-auto text-xs text-[var(--c-muted)]">{table.type}</span>
                </label>
              )
            })}
          </div>
          <Button onClick={startSnapshot} disabled={busy || selectedTables.length === 0}>Import selected snapshot</Button>
        </div>
      )}

      {message && (
        <div role="status" className={`rounded-lg border p-3 text-sm ${state === 'failed' ? 'border-red-500/40 text-red-300' : state === 'test-success' || state === 'ready' || state === 'started' ? 'border-emerald-500/40 text-emerald-300' : 'border-brand-600/40 text-[var(--c-muted)]'}`}>
          {busy && <Loader className="inline w-4 h-4 mr-2 animate-spin" />}{message}
        </div>
      )}
    </Card>
  )
}

// Upload Area Component
function UploadArea({ isDragging, isUploading, uploadProgress, onDragOver, onDragLeave, onDrop, onFileSelect }) {
  const fileInputRef = useState(null)[0]

  return (
    <Card className="p-8">
        <div
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          className={`
            relative border-2 border-dashed rounded-xl p-12 text-center transition-all duration-300
            ${isDragging 
              ? 'border-brand-400 bg-brand-900/30'
              : 'border-brand-700/40 hover:border-brand-300 hover:bg-[rgba(255,255,255,0.04)]'
            }
            ${isUploading ? 'pointer-events-none opacity-60' : ''}
          `}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => onFileSelect(e.target.files[0])}
            className="hidden"
            id="file-upload"
          />

          {isUploading ? (
            <motion.div
              variants={scaleIn}
              initial="hidden"
              animate="visible"
              className="space-y-4"
            >
              <Loader className="w-16 h-16 mx-auto text-brand-500 animate-spin" />
              <div>
                <p className="text-lg font-semibold text-white">Uploading...</p>
                <p className="text-sm text-[var(--c-muted)] mt-1">{uploadProgress}% complete</p>
              </div>
              <div className="w-full max-w-md mx-auto bg-brand-700/30 rounded-full h-2">
                <motion.div
                  className="bg-brand-500 h-2 rounded-full"
                  initial={{ width: 0 }}
                  animate={{ width: `${uploadProgress}%` }}
                  transition={{ duration: 0.3 }}
                />
              </div>
            </motion.div>
          ) : (
            <motion.div variants={scaleIn} className="space-y-4">
              <motion.div
                animate={isDragging ? { scale: 1.1 } : { scale: 1 }}
                transition={{ duration: 0.2 }}
              >
                <Upload className="w-16 h-16 mx-auto text-brand-300/60" />
              </motion.div>
              
              <div>
                <label htmlFor="file-upload" className="cursor-pointer">
                  <span className="text-lg font-semibold text-brand-500 hover:text-brand-300">
                    Click to upload
                  </span>
                  <span className="text-[var(--c-muted)]"> or drag and drop</span>
                </label>
                <p className="text-sm text-brand-300/80 mt-2">
                  CSV, XLSX, or XLS files
                </p>
              </div>

              <Button
                variant="primary"
                icon={Upload}
                onClick={() => document.getElementById('file-upload').click()}
                className="mt-4"
              >
                Select File
              </Button>
            </motion.div>
          )}
        </div>
      </Card>
  )
}

// Database Info Component
function DatabaseInfo({ database }) {
  const formatFileSize = (bytes) => {
    if (!bytes) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
  }

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleString()
  }

  const statusConfig = {
    pending: { color: 'gray', icon: AlertCircle, text: 'Pending' },
    processing: { color: 'blue', icon: Loader, text: 'Processing' },
    completed: { color: 'green', icon: CheckCircle, text: 'Completed' },
    failed: { color: 'red', icon: AlertCircle, text: 'Failed' }
  }

  const status = statusConfig[database.etl_status] || statusConfig.pending
  const StatusIcon = status.icon

  return (
    <Card>
        <div className="p-6">
          <div className="flex items-center space-x-3 mb-6">
            <div className="p-3 bg-brand-700/30 rounded-lg">
              <DatabaseIcon className="w-6 h-6 text-brand-500" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-white">Database Information</h2>
              <p className="text-sm text-[var(--c-muted)]">Overview of your uploaded database</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <InfoItem
              icon={FileText}
              label="Filename"
              value={database.filename}
            />
            <InfoItem
              icon={Info}
              label="File Size"
              value={database.file_size_formatted || formatFileSize(database.file_size)}
            />
            <InfoItem
              icon={Table}
              label="Rows"
              value={database.row_count?.toLocaleString() || '-'}
            />
            <InfoItem
              icon={Table}
              label="Columns"
              value={database.column_count?.toLocaleString() || '-'}
            />
            <InfoItem
              icon={CheckCircle}
              label="Upload Date"
              value={formatDate(database.upload_date)}
            />
            <InfoItem
              icon={StatusIcon}
              label="Status"
              value={
                <span className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-${status.color}-100 text-${status.color}-700`}>
                  <StatusIcon className={`w-4 h-4 mr-1 ${database.etl_status === 'processing' ? 'animate-spin' : ''}`} />
                  {status.text}
                </span>
              }
            />
          </div>
        </div>
      </Card>
  )
}

// Info Item Component
function InfoItem({ icon: Icon, label, value }) {
  return (
    <div className="flex items-start space-x-3">
      <div className="p-2 bg-[rgba(255,255,255,0.07)] rounded-lg">
        <Icon className="w-5 h-5 text-[var(--c-muted)]" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-brand-300/80">{label}</p>
        <p className="text-base font-semibold text-white truncate mt-1">{value}</p>
      </div>
    </div>
  )
}

function ImportedTableSelector({ tables, selectedTableId, disabled, onSelect }) {
  return (
    <Card>
      <div className="p-6">
        <h3 className="text-lg font-bold text-white mb-3">Imported tables</h3>
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Imported tables">
          {tables.map((table) => {
            const label = table.schema ? `${table.schema}.${table.name}` : table.name
            const active = table.id === selectedTableId
            return (
              <button
                key={table.id || label}
                type="button"
                role="tab"
                aria-selected={active}
                disabled={disabled}
                onClick={() => onSelect(table.id)}
                className={`rounded-lg border px-4 py-2 text-sm transition ${
                  active
                    ? 'border-brand-500 bg-brand-700/40 text-white'
                    : 'border-brand-700/40 bg-[var(--c-surface)] text-[var(--c-muted)] hover:text-white'
                } disabled:opacity-50`}
              >
                {label}
                {Number.isInteger(table.row_count) && (
                  <span className="ml-2 text-xs opacity-75">{table.row_count.toLocaleString()} rows</span>
                )}
              </button>
            )
          })}
        </div>
      </div>
    </Card>
  )
}

// Schema Preview Component
function SchemaPreview({ schema }) {
  return (
    <Card>
        <div className="p-6">
          <h3 className="text-lg font-bold text-white mb-4">Schema Information</h3>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-brand-700/30">
              <thead className="bg-[rgba(255,255,255,0.04)]">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-brand-300/80 uppercase tracking-wider">
                    Column Name
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-brand-300/80 uppercase tracking-wider">
                    Data Type
                  </th>
                </tr>
              </thead>
              <tbody className="bg-[var(--c-card-bg)] divide-y divide-brand-700/30">
                {schema.columns.map((column, idx) => (
                  <motion.tr
                    key={idx}
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: idx * 0.05 }}
                  >
                    <td className="px-4 py-3 text-sm font-medium text-white">
                      {column}
                    </td>
                    <td className="px-4 py-3 text-sm text-[var(--c-muted)]">
                      <code className="px-2 py-1 bg-[rgba(255,255,255,0.07)] rounded text-xs">
                        {schema.column_types?.[column] || 'String'}
                      </code>
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Card>
  )
}

// Data Preview Component
function DataPreview({ previewData, isLoading }) {
  if (isLoading) {
    return (
      <Card>
        <div className="p-6">
          <div className="flex items-center justify-center py-12">
            <LoadingSpinner />
          </div>
        </div>
      </Card>
    )
  }

  return (
    <Card>
      <div className="p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-bold text-white">Data Preview</h3>
          <span className="text-sm text-[var(--c-muted)]">First 5 rows</span>
        </div>
          
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-brand-700/30">
              <thead className="bg-[rgba(255,255,255,0.04)]">
                <tr>
                  {previewData.columns.map((column, idx) => (
                    <th
                      key={idx}
                      className="px-4 py-3 text-left text-xs font-medium text-brand-300/80 uppercase tracking-wider whitespace-nowrap"
                    >
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="bg-[var(--c-card-bg)] divide-y divide-brand-700/30">
                {previewData.rows.map((row, rowIdx) => (
                  <motion.tr
                    key={rowIdx}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: rowIdx * 0.1 }}
                  >
                    {previewData.columns.map((column, colIdx) => (
                      <td
                        key={colIdx}
                        className="px-4 py-3 text-sm text-white whitespace-nowrap"
                      >
                        {row[column] !== null && row[column] !== undefined 
                          ? String(row[column]) 
                          : '-'}
                      </td>
                    ))}
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 text-sm text-[var(--c-muted)] text-center">
          Showing 5 of {previewData.total_rows?.toLocaleString()} rows
        </div>
      </div>
    </Card>
  )
}

// Processing Card Component
function ProcessingCard() {
  return (
    <Card>
        <div className="p-6 text-center">
          <Loader className="w-12 h-12 mx-auto text-brand-500 animate-spin mb-4" />
          <h3 className="text-lg font-semibold text-white mb-2">Processing Your Data</h3>
          <p className="text-[var(--c-muted)]">
            Your database is being processed through the ETL pipeline. This may take a few moments.
          </p>
        </div>
      </Card>
  )
}

// Error Card Component
function ErrorCard({ message }) {
  return (
    <Card>
        <div className="p-6">
          <div className="flex items-start space-x-3 p-4 bg-red-50 border border-red-200 rounded-lg">
            <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <h4 className="font-semibold text-red-900 mb-1">Processing Failed</h4>
              <p className="text-sm text-red-700">
                {message || 'An error occurred while processing your database.'}
              </p>
            </div>
          </div>
        </div>
      </Card>
  )
}

export default DatabaseManagement


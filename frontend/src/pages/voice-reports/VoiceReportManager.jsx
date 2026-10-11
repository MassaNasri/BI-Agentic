import { useState, useEffect, useMemo } from 'react'
import { motion } from 'framer-motion'
import { toast } from 'react-hot-toast'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { 
  Mic, 
  Upload, 
  Trash2, 
  Database,
  Clock,
  BarChart3,
  CheckCircle,
  XCircle,
  Loader,
  Code,
  MessageSquare
} from 'lucide-react'

import { voiceReportsAPI, subscriptionAPI } from '../../api/endpoints'
import { useAuthStore } from '../../store/auth'
import AnimatedPage from '../../components/AnimatedPage'
import Card from '../../components/Card'
import Button from '../../components/Button'
import Modal from '../../components/Modal'
import SubscriptionPlansPanel from '../../components/subscription/SubscriptionPlansPanel'
import { fadeIn, slideInBottom } from '../../animations/variants'
import {
  isReportCompleted,
  isReportFailed,
  getReportStatusBadgeClass,
  formatReportStatus,
} from '../../utils/reportStatus'
import { withNightEmbedAppearance } from '../../utils/embedAppearance'
import { describeVoiceWorkflowError } from '../../utils/voiceWorkflowError'

function VoiceReportManager() {
  const { user, workspace } = useAuthStore()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const selectedReportIdParam = searchParams.get('reportId')
  const attachPageId = useMemo(() => {
    const rawValue = searchParams.get('attachPageId')
    if (!rawValue) return null
    const parsedValue = Number(rawValue)
    if (!Number.isInteger(parsedValue) || parsedValue <= 0) return null
    return parsedValue
  }, [searchParams])
  const returnToPath = useMemo(() => {
    const rawPath = searchParams.get('returnTo')
    return rawPath ? String(rawPath) : ''
  }, [searchParams])
  const [currentReport, setCurrentReport] = useState(null)
  const [reports, setReports] = useState([])
  const [isUploading, setIsUploading] = useState(false)
  const [isExecuting, setIsExecuting] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [selectedFile, setSelectedFile] = useState(null)
  const [inputMode, setInputMode] = useState('voice')
  const [textInput, setTextInput] = useState('')
  const [isSubmittingText, setIsSubmittingText] = useState(false)
  const [processingPhase, setProcessingPhase] = useState('') // 'transcribing' | 'classifying' | 'generating' | 'executing' | 'rendering'
  const [showSubscriptionModal, setShowSubscriptionModal] = useState(false)
  const [showUsageModal, setShowUsageModal] = useState(false)
  const [usageLoading, setUsageLoading] = useState(false)
  const [usageError, setUsageError] = useState('')
  const [usageData, setUsageData] = useState(null)

  const workspaceId = useMemo(() => {
    if (workspace?.id) return workspace.id
    if (user?.workspace?.id) return user.workspace.id
    if (Array.isArray(workspace) && workspace.length > 0) return workspace[0]?.id || null
    return null
  }, [workspace, user])

  useEffect(() => {
    loadReports()
  }, [])

  const loadReports = async () => {
    try {
      const response = await voiceReportsAPI.listReports({ lite: true })
      if (response.data.success) {
        setReports(response.data.reports || [])
      }
    } catch (error) {
      console.error('Failed to load reports:', error)
    }
  }

  const handleFileSelect = (event) => {
    const file = event.target.files[0]
    if (!file) return

    // Validate file type
    const validTypes = ['audio/wav', 'audio/mpeg', 'audio/mp3', 'audio/ogg', 'audio/webm']
    if (!validTypes.includes(file.type)) {
      toast.error('Please upload a valid audio file (WAV, MP3, OGG, WebM)')
      return
    }

    // Validate file size (max 50MB)
    if (file.size > 50 * 1024 * 1024) {
      toast.error('Audio file must be less than 50MB')
      return
    }

    setSelectedFile(file)
  }

  const isProcessingRequest = isUploading || isSubmittingText || isExecuting
  const isPrimaryStepComplete = ['generating', 'executing', 'rendering'].includes(processingPhase)
  const isPrimaryStepActive = processingPhase === 'transcribing' || processingPhase === 'classifying'
  const formatConfidence = (value) => {
    const numeric = Number(value)
    if (!Number.isFinite(numeric)) return '-'
    return `${Math.round(Math.max(0, Math.min(1, numeric)) * 100)}%`
  }

  const handleSubmissionResult = async (response, sourceMode) => {
    if (!response.data.success) {
      toast.error(response.data.error || 'Request failed')
      const message = response.data.message || response.data.error || ''
      if (String(message).toLowerCase().includes('reached your limit')) {
        setShowSubscriptionModal(true)
      }
      return
    }

    const reportId = response.data.report_id || response.data.id
    if (!reportId) {
      toast.error('Request succeeded but no report ID was returned. Please try again.')
      return
    }

    const questionType = String(response.data.question_type || '').trim().toLowerCase()
    const nonAnalyticalTypes = new Set([
      'conversational',
      'informational',
      'invalid_input',
      'numeric_only_input',
      'noise_input',
      'empty_input',
      'transcription_failure',
      'no_speech_detected'
    ])
    const isExplicitNonAnalytical = nonAnalyticalTypes.has(questionType)
    const hasSql = Boolean(response.data.sql && String(response.data.sql).trim())

    if (isExplicitNonAnalytical) {
      toast.success(
        sourceMode === 'voice'
          ? 'Audio transcribed! This appears to be a conversational question and does not require data analysis.'
          : 'Text processed! This appears to be a conversational question and does not require data analysis.'
      )
      setCurrentReport({
        id: reportId,
        transcription: response.data.transcription,
        sql: null,
        intent: response.data.intent,
        status: 'uploaded',
        message: response.data.message,
        confidence: response.data.confidence,
        degraded: response.data.degraded,
      })
      setSelectedFile(null)
      setTextInput('')
      await loadReports()
      return
    }

    if (!hasSql) {
      const fallbackMessage =
        response.data.message ||
        response.data.error ||
        'The request could not be processed into SQL. Please try rephrasing the question.'
      toast.error(fallbackMessage)
      setCurrentReport({
        id: reportId,
        transcription: response.data.transcription,
        sql: null,
        intent: response.data.intent,
        status: response.data.status || 'failed',
        message: fallbackMessage,
        confidence: response.data.confidence,
        degraded: response.data.degraded,
      })
      setSelectedFile(null)
      setTextInput('')
      await loadReports()
      return
    }

    setProcessingPhase('generating')
    toast.success(
      sourceMode === 'voice'
        ? 'Audio transcribed! Generating SQL query...'
        : 'Text received! Generating SQL query...'
    )

    setProcessingPhase('executing')
    const executeResponse = await voiceReportsAPI.executeQuery(reportId)

    if (executeResponse.data.success) {
      setProcessingPhase('rendering')
      await new Promise(resolve => setTimeout(resolve, 500))

      if (executeResponse.data.degraded) {
        toast.success(`Chart generated with reduced confidence. ${executeResponse.data.row_count} rows visualized`)
      } else {
        toast.success(`Chart generated! ${executeResponse.data.row_count} rows visualized`)
      }

      setCurrentReport({
        id: reportId,
        transcription: response.data.transcription,
        sql: response.data.sql,
        intent: response.data.intent,
        status: executeResponse.data.status || 'visualization_created',
        embedUrl: executeResponse.data.embed_url,
        rowCount: executeResponse.data.row_count,
        executionTime: executeResponse.data.execution_time_ms,
        chartType: executeResponse.data.chart_type,
        confidence: executeResponse.data.confidence ?? response.data.confidence,
        degraded: Boolean(executeResponse.data.degraded ?? response.data.degraded),
      })

      setSelectedFile(null)
      setTextInput('')
      await loadReports()
      if (attachPageId) {
        try {
          const attachResponse = await voiceReportsAPI.createDashboardWidget(attachPageId, {
            report_id: reportId,
            width: 6,
            height: 4,
          })
          if (!attachResponse.data?.success) {
            throw new Error(attachResponse.data?.error || 'Failed to attach report to dashboard page.')
          }
          toast.success('Report added to dashboard page.')
          if (returnToPath) {
            navigate(returnToPath)
          }
        } catch (attachError) {
          console.error('Failed to auto-attach created report:', attachError)
          toast.error(attachError.response?.data?.error || attachError.message || 'Failed to attach report to dashboard page.')
        }
      }
      return
    }

    toast.error(executeResponse.data.error || 'Chart generation failed')
    setCurrentReport({
      id: reportId,
      transcription: response.data.transcription,
        sql: response.data.sql,
        intent: response.data.intent,
        status: 'failed',
        confidence: response.data.confidence,
        degraded: response.data.degraded,
      })
  }

  const handleUpload = async () => {
    if (!selectedFile) {
      toast.error('Please select an audio file first')
      return
    }

    setIsUploading(true)
    setUploadProgress(0)
    setIsExecuting(true)
    setProcessingPhase('transcribing')

    try {
      const response = await voiceReportsAPI.uploadAudio(selectedFile, (progressEvent) => {
        const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total)
        setUploadProgress(percentCompleted)
      })
      await handleSubmissionResult(response, 'voice')
    } catch (error) {
      console.error('Processing error:', error)
      const describedError = describeVoiceWorkflowError(error)
      toast.error(describedError.message)
      if (describedError.shouldShowSubscription) {
        setShowSubscriptionModal(true)
      }
    } finally {
      setIsUploading(false)
      setIsExecuting(false)
      setUploadProgress(0)
      setProcessingPhase('')
    }
  }

  const handleTextSubmit = async () => {
    const text = textInput.trim()
    if (!text) {
      return
    }

    setIsSubmittingText(true)
    setIsExecuting(true)
    setProcessingPhase('classifying')

    try {
      const response = await voiceReportsAPI.submitTextQuery(text, workspaceId)
      await handleSubmissionResult(response, 'text')
    } catch (error) {
      console.error('Text processing error:', error)
      const describedError = describeVoiceWorkflowError(error)
      toast.error(describedError.message)
      if (describedError.shouldShowSubscription) {
        setShowSubscriptionModal(true)
      }
    } finally {
      setIsSubmittingText(false)
      setIsExecuting(false)
      setProcessingPhase('')
    }
  }
  // Manager doesn't need manual execute - auto-execute happens during upload

  const handleDeleteReport = async (reportId) => {
    if (!confirm('Are you sure you want to delete this report?')) return

    try {
      const response = await voiceReportsAPI.deleteReport(reportId)
      
      if (response.data.success) {
        toast.success('Report deleted successfully')
        
        if (currentReport?.id === reportId) {
          setCurrentReport(null)
        }
        
        loadReports()
      }
    } catch (error) {
      console.error('Delete error:', error)
      toast.error('Failed to delete report')
    }
  }

  const handleLoadReport = async (reportId) => {
    try {
      const response = await voiceReportsAPI.getReport(reportId)
      
      if (response.data.success) {
        const report = response.data.report
        setCurrentReport({
          id: report.id,
          transcription: report.transcription,
          sql: report.final_sql,
          intent: report.intent,
          status: report.status,
          embedUrl: report.embed_url,
          rowCount: report.row_count,
          executionTime: report.execution_time_ms,
          chartType: report.chart_type,
          confidence: report.confidence,
          degraded: report.degraded,
        })
      }
    } catch (error) {
      console.error('Failed to load report:', error)
      toast.error('Failed to load report')
    }
  }

  useEffect(() => {
    if (!selectedReportIdParam) {
      return
    }
    const parsedReportId = Number(selectedReportIdParam)
    if (Number.isNaN(parsedReportId)) {
      return
    }
    handleLoadReport(parsedReportId)
  }, [selectedReportIdParam])

  const handleOpenUsageModal = async () => {
    if (!workspaceId) {
      toast.error('Workspace is required to check subscription usage.')
      return
    }

    setShowUsageModal(true)
    setUsageLoading(true)
    setUsageError('')

    try {
      const response = await subscriptionAPI.checkAccess(workspaceId, false)
      if (response.data?.success) {
        setUsageData({
          limit: Number(response.data.limit || 0),
          used: Number(response.data.used_requests || 0),
          remaining: Number(response.data.remaining_requests || 0),
          isSubscribed: Boolean(response.data.is_subscribed),
          planName: response.data.plan?.name || 'Free Tier',
        })
      } else {
        setUsageData(null)
        setUsageError(response.data?.message || 'Unable to load usage right now.')
      }
    } catch (error) {
      setUsageData(null)
      setUsageError(error.response?.data?.message || 'Failed to load subscription usage.')
    } finally {
      setUsageLoading(false)
    }
  }

  return (
    <AnimatedPage>
      <div className="space-y-6">
        {/* Header */}
        <motion.div variants={fadeIn}>
          <h1 className="text-3xl font-bold text-white dark:text-white">
            🎙️ Voice-Driven BI Reports
          </h1>
          <p className="mt-2 text-[var(--c-muted)] dark:text-brand-300/60">
            Ask with voice or text and get instant AI-powered visualizations. No SQL knowledge required.
          </p>
        </motion.div>

        {/* Input Mode */}
        <motion.div variants={slideInBottom}>
          <div className="inline-flex rounded-lg border border-brand-700/30 bg-[var(--c-card-bg)] p-1 shadow-sm dark:border-brand-700/40 dark:bg-brand-950">
            <button
              type="button"
              className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
                inputMode === 'voice'
                  ? 'bg-brand-500 text-white'
                  : 'text-[var(--c-muted)] hover:text-white dark:text-brand-200/70 dark:hover:text-white'
              }`}
              onClick={() => setInputMode('voice')}
              disabled={isProcessingRequest}
            >
              Voice
            </button>
            <button
              type="button"
              className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
                inputMode === 'text'
                  ? 'bg-brand-500 text-white'
                  : 'text-[var(--c-muted)] hover:text-white dark:text-brand-200/70 dark:hover:text-white'
              }`}
              onClick={() => setInputMode('text')}
              disabled={isProcessingRequest}
            >
              Text
            </button>
          </div>
        </motion.div>

        {/* Input Section */}
        <motion.div variants={slideInBottom}>
          <Card>
            <h2 className="text-xl font-semibold mb-4 text-white dark:text-white">
              {inputMode === 'voice' ? 'Upload Audio' : 'Enter Text'}
            </h2>

            <div className="space-y-4">
              {inputMode === 'voice' ? (
                <>
                  <div className="flex items-center gap-4">
                    <label className="flex-1">
                      <div className="flex items-center justify-center w-full h-32 px-4 transition bg-[var(--c-card-bg)] border-2 border-brand-700/40 border-dashed rounded-lg appearance-none cursor-pointer hover:border-brand-400 focus:outline-none dark:bg-brand-900 dark:border-brand-700/40 dark:hover:border-brand-400">
                        <div className="flex flex-col items-center space-y-2">
                          <Upload className="w-8 h-8 text-[var(--c-muted)] dark:text-brand-300/60" />
                          <span className="text-sm text-[var(--c-muted)] dark:text-brand-300/60">
                            {selectedFile ? selectedFile.name : 'Click to select audio file'}
                          </span>
                          <span className="text-xs text-brand-300/80">
                            WAV, MP3, OGG, WebM (max 50MB)
                          </span>
                        </div>
                        <input
                          type="file"
                          className="hidden"
                          accept="audio/*"
                          onChange={handleFileSelect}
                          disabled={isUploading}
                        />
                      </div>
                    </label>
                  </div>

                  <Button
                    onClick={handleUpload}
                    disabled={!selectedFile || isUploading}
                    className="w-full"
                  >
                    {isUploading ? (
                      <>
                        <Loader className="w-5 h-5 animate-spin mr-2" />
                        Processing Audio...
                      </>
                    ) : (
                      <>
                        <Upload className="w-5 h-5 mr-2" />
                        Upload and Process
                      </>
                    )}
                  </Button>
                </>
              ) : (
                <>
                  <textarea
                    className="w-full min-h-32 rounded-lg border border-brand-700/40 bg-[var(--c-card-bg)] px-4 py-3 text-sm text-white focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-400/20 dark:border-brand-700/40 dark:bg-brand-900 dark:text-white"
                    placeholder="Type your business question..."
                    value={textInput}
                    onChange={(event) => setTextInput(event.target.value)}
                    disabled={isSubmittingText}
                  />
                  <Button
                    onClick={handleTextSubmit}
                    disabled={!textInput.trim() || isSubmittingText}
                    className="w-full"
                  >
                    {isSubmittingText ? (
                      <>
                        <Loader className="w-5 h-5 animate-spin mr-2" />
                        Processing Text...
                      </>
                    ) : (
                      <>
                        <MessageSquare className="w-5 h-5 mr-2" />
                        Send
                      </>
                    )}
                  </Button>
                </>
              )}

              {inputMode === 'voice' && isUploading && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-[var(--c-muted)] dark:text-brand-300/60">Uploading...</span>
                    <span className="text-white dark:text-white font-medium">{uploadProgress}%</span>
                  </div>
                  <div className="w-full bg-brand-700/30 rounded-full h-2 dark:bg-brand-800/70">
                    <div
                      className="bg-brand-500 h-2 rounded-full transition-all duration-300"
                      style={{ width: `${uploadProgress}%` }}
                    />
                  </div>
                </div>
              )}

              {processingPhase && (
                <div className="space-y-3 p-4 bg-brand-900/30 dark:bg-brand-100/20 rounded-lg border-2 border-brand-700/40 dark:border-brand-200">
                  <div className="flex items-center gap-3">
                    <Loader className="w-5 h-5 text-brand-500 animate-spin" />
                    <span className="font-semibold text-brand-100 dark:text-brand-700/30">
                      {inputMode === 'voice' ? 'Processing Your Audio...' : 'Processing Your Text...'}
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg flex-1 transition-all ${
                      isPrimaryStepActive
                        ? 'bg-brand-500 text-white shadow-md'
                        : isPrimaryStepComplete
                        ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                        : 'bg-brand-700/30 text-[var(--c-muted)] dark:bg-brand-800/70 dark:text-brand-300/60'
                    }`}>
                      {inputMode === 'voice' ? <Mic className="w-4 h-4" /> : <MessageSquare className="w-4 h-4" />}
                      <span className="text-xs font-medium">{inputMode === 'voice' ? 'Transcribing' : 'Classifying'}</span>
                    </div>

                    <div className="text-brand-300/60">-&gt;</div>

                    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg flex-1 transition-all ${
                      processingPhase === 'generating'
                        ? 'bg-brand-500 text-white shadow-md'
                        : processingPhase === 'executing' || processingPhase === 'rendering'
                        ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                        : 'bg-brand-700/30 text-[var(--c-muted)] dark:bg-brand-800/70 dark:text-brand-300/60'
                    }`}>
                      <Code className="w-4 h-4" />
                      <span className="text-xs font-medium">Generating</span>
                    </div>

                    <div className="text-brand-300/60">-&gt;</div>

                    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg flex-1 transition-all ${
                      processingPhase === 'executing'
                        ? 'bg-brand-500 text-white shadow-md'
                        : processingPhase === 'rendering'
                        ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                        : 'bg-brand-700/30 text-[var(--c-muted)] dark:bg-brand-800/70 dark:text-brand-300/60'
                    }`}>
                      <Database className="w-4 h-4" />
                      <span className="text-xs font-medium">Executing</span>
                    </div>

                    <div className="text-brand-300/60">-&gt;</div>

                    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg flex-1 transition-all ${
                      processingPhase === 'rendering'
                        ? 'bg-brand-500 text-white shadow-md'
                        : 'bg-brand-700/30 text-[var(--c-muted)] dark:bg-brand-800/70 dark:text-brand-300/60'
                    }`}>
                      <BarChart3 className="w-4 h-4" />
                      <span className="text-xs font-medium">Rendering</span>
                    </div>
                  </div>
                </div>
              )}

              <Button
                variant="outline"
                className="w-full"
                onClick={handleOpenUsageModal}
              >
                Manage Subscription
              </Button>
            </div>
          </Card>
        </motion.div>

        {/* Current Report */}
        {currentReport && (
          <motion.div variants={slideInBottom}>
            <Card>
              <h2 className="text-xl font-semibold mb-4 text-white dark:text-white flex items-center gap-2">
                <BarChart3 className="w-6 h-6 text-brand-500" />
                Your Generated Chart
              </h2>

              {/* Results */}
              {isReportCompleted(currentReport.status) && (
                <>
                  {/* Metrics */}
                  <div className="grid grid-cols-1 gap-4 mb-6 md:grid-cols-4">
                    <div className="p-4 bg-green-50 dark:bg-green-900/20 rounded-lg">
                      <div className="flex items-center gap-2 text-green-600 dark:text-green-400 mb-1">
                        <Database className="w-4 h-4" />
                        <span className="text-sm font-medium">Rows</span>
                      </div>
                      <p className="text-2xl font-bold text-white dark:text-white">
                        {currentReport.rowCount?.toLocaleString() || 0}
                      </p>
                    </div>

                    <div className="p-4 bg-brand-900/30 dark:bg-brand-100/20 rounded-lg">
                      <div className="flex items-center gap-2 text-brand-500 dark:text-brand-300 mb-1">
                        <Clock className="w-4 h-4" />
                        <span className="text-sm font-medium">Time</span>
                      </div>
                      <p className="text-2xl font-bold text-white dark:text-white">
                        {currentReport.executionTime}ms
                      </p>
                    </div>

                    <div className="p-4 bg-brand-900/30 dark:bg-brand-100/20 rounded-lg">
                      <div className="flex items-center gap-2 text-brand-500 dark:text-brand-300 mb-1">
                        <BarChart3 className="w-4 h-4" />
                        <span className="text-sm font-medium">Chart Type</span>
                      </div>
                      <p className="text-2xl font-bold text-white dark:text-white capitalize">
                        {currentReport.chartType}
                      </p>
                    </div>

                    <div className="p-4 bg-amber-500/15 dark:bg-amber-400/20 rounded-lg">
                      <div className="flex items-center gap-2 text-amber-400 dark:text-amber-400 mb-1">
                        <CheckCircle className="w-4 h-4" />
                        <span className="text-sm font-medium">Confidence</span>
                      </div>
                      <p className="text-2xl font-bold text-white dark:text-white">
                        {formatConfidence(currentReport.confidence)}
                      </p>
                      {currentReport.degraded && (
                        <p className="mt-1 text-xs font-medium text-amber-400 dark:text-amber-400">
                          Degraded
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Embedded Visualization */}
                  {currentReport.embedUrl && (
                    <div className="mb-4">
                      <div className="rounded-xl border border-brand-600/40 bg-[var(--c-report-bg)] overflow-hidden shadow-[0_18px_50px_rgba(0,0,0,0.45)]">
                        <iframe
                          src={withNightEmbedAppearance(currentReport.embedUrl)}
                          width="100%"
                          height="600"
                          frameBorder="0"
                          className="bg-[var(--c-report-bg)]"
                          title="Data Visualization"
                          loading="lazy"
                        />
                      </div>
                    </div>
                  )}

                  {/* Success Message */}
                  <div className="flex items-center gap-3 p-4 bg-green-50 dark:bg-green-900/20 rounded-lg border border-green-200 dark:border-green-800">
                    <CheckCircle className="w-5 h-5 text-green-600 dark:text-green-400 flex-shrink-0" />
                    <div>
                      <p className="font-medium text-green-900 dark:text-green-100">
                        ✅ Chart Generated Successfully
                      </p>
                      <p className="text-sm text-green-700 dark:text-green-300">
                        Your data has been analyzed and visualized. The chart is now available in your dashboard.
                      </p>
                    </div>
                  </div>
                </>
              )}

              {/* Failed State */}
              {isReportFailed(currentReport.status) && (
                <div className="flex items-center gap-3 p-4 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800">
                  <XCircle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0" />
                  <div>
                    <p className="font-medium text-red-900 dark:text-red-100">
                      ❌ Chart Generation Failed
                    </p>
                    <p className="text-sm text-red-700 dark:text-red-300">
                      There was an error processing your request. Please try again.
                    </p>
                  </div>
                </div>
              )}
            </Card>
          </motion.div>
        )}

        {/* Reports History */}
        <motion.div variants={slideInBottom}>
          <Card>
            <h2 className="text-xl font-semibold mb-4 text-white dark:text-white">
              Your Reports
            </h2>

            {reports.length === 0 ? (
              <div className="text-center py-12">
                <Mic className="w-16 h-16 mx-auto text-brand-300/60 mb-4" />
                <p className="text-brand-300/80 dark:text-brand-300/60">
                  No reports yet. Submit voice or text input to get started!
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {reports.map((report) => (
                  <div
                    key={report.id}
                    className="flex items-center justify-between p-4 bg-[rgba(255,255,255,0.04)] dark:bg-brand-900 rounded-lg hover:bg-[rgba(255,255,255,0.07)] dark:hover:bg-brand-800/70 transition-colors cursor-pointer"
                    onClick={() => handleLoadReport(report.id)}
                  >
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-1">
                        <h3 className="font-medium text-white dark:text-white">
                          Report #{report.id}
                        </h3>
                        <span className={`
                          px-2 py-1 text-xs rounded-full font-medium
                          ${getReportStatusBadgeClass(report.status)}
                        `}>
                          {isReportCompleted(report.status) && <CheckCircle className="w-3 h-3 inline mr-1" />}
                          {isReportFailed(report.status) && <XCircle className="w-3 h-3 inline mr-1" />}
                          {formatReportStatus(report.status)}
                        </span>
                      </div>
                      {report.row_count && (
                        <p className="text-xs text-brand-300/80 dark:text-brand-300/80 mt-1">
                          <Database className="w-3 h-3 inline mr-1" />
                          {report.row_count.toLocaleString()} rows • 
                          <BarChart3 className="w-3 h-3 inline ml-2 mr-1" />
                          {report.chart_type} chart
                        </p>
                      )}
                    </div>

                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDeleteReport(report.id)
                      }}
                      className="ml-4 p-2 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
                    >
                      <Trash2 className="w-5 h-5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </motion.div>

        <Modal
          isOpen={showUsageModal}
          onClose={() => setShowUsageModal(false)}
          title="Subscription Usage"
          size="sm"
        >
          <div className="space-y-4">
            {usageLoading ? (
              <p className="text-sm text-[var(--c-muted)]">Loading usage...</p>
            ) : usageError ? (
              <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {usageError}
              </div>
            ) : usageData ? (
              <div className="space-y-3">
                <div className="rounded-lg border border-brand-700/30 bg-[rgba(255,255,255,0.04)] p-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-300/80">Plan</p>
                  <p className="mt-1 text-sm font-medium text-white">{usageData.planName}</p>
                </div>
                <div className="rounded-lg border border-brand-700/40 bg-brand-900/30 p-3">
                  <p className="text-sm font-medium text-brand-100">Usage</p>
                  <p className="mt-1 text-sm text-brand-200">
                    {usageData.used} / {usageData.limit} requests used
                  </p>
                  <p className="mt-1 text-sm text-brand-200">{usageData.remaining} remaining</p>
                </div>
              </div>
            ) : (
              <p className="text-sm text-[var(--c-muted)]">No usage details available.</p>
            )}

            <div className="flex items-center justify-end gap-2">
              <Button type="button" variant="secondary" onClick={() => setShowUsageModal(false)}>
                Close
              </Button>
            </div>
          </div>
        </Modal>

        <Modal
          isOpen={showSubscriptionModal}
          onClose={() => setShowSubscriptionModal(false)}
          title="Upgrade Subscription"
          size="xl"
        >
          <SubscriptionPlansPanel
            workspaceId={workspaceId}
            title="Unlock More Voice Requests"
            onSubscribed={() => setShowSubscriptionModal(false)}
          />
        </Modal>
      </div>
    </AnimatedPage>
  )
}

export default VoiceReportManager




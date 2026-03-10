import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { toast } from 'react-hot-toast'
import { useSearchParams } from 'react-router-dom'
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
  Code
} from 'lucide-react'

import { voiceReportsAPI } from '../../api/endpoints'
import AnimatedPage from '../../components/AnimatedPage'
import Card from '../../components/Card'
import Button from '../../components/Button'
import { fadeIn, slideInBottom } from '../../animations/variants'
import {
  isReportCompleted,
  isReportFailed,
  getReportStatusBadgeClass,
  formatReportStatus,
} from '../../utils/reportStatus'

function VoiceReportManager() {
  const [searchParams] = useSearchParams()
  const selectedReportIdParam = searchParams.get('reportId')
  const [currentReport, setCurrentReport] = useState(null)
  const [reports, setReports] = useState([])
  const [isUploading, setIsUploading] = useState(false)
  const [isExecuting, setIsExecuting] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [selectedFile, setSelectedFile] = useState(null)
  const [processingPhase, setProcessingPhase] = useState('') // 'transcribing', 'generating', 'executing', 'rendering'

  useEffect(() => {
    loadReports()
  }, [])

  const loadReports = async () => {
    try {
      const response = await voiceReportsAPI.listReports()
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
      // Phase 1: Upload & Transcribe
      const response = await voiceReportsAPI.uploadAudio(selectedFile, (progressEvent) => {
        const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total)
        setUploadProgress(percentCompleted)
      })

      if (!response.data.success) {
        toast.error(response.data.error || 'Upload failed')
        setIsUploading(false)
        setIsExecuting(false)
        setProcessingPhase('')
        return
      }

      const reportId = response.data.report_id || response.data.id

      // Validate report_id exists before proceeding
      if (!reportId) {
        toast.error('Upload succeeded but no report ID was returned. Please try again.')
        setIsUploading(false)
        setIsExecuting(false)
        setProcessingPhase('')
        return
      }

      // Check if this is a conversational question (no SQL)
      if (response.data.requires_sql === false || !response.data.sql) {
        toast.success('Audio transcribed! This appears to be a conversational question and does not require data analysis.')
        setCurrentReport({
          id: reportId,
          transcription: response.data.transcription,
          sql: null,
          intent: response.data.intent,
          status: 'uploaded',
          message: response.data.message
        })
        setSelectedFile(null)
        loadReports()
        setIsUploading(false)
        setIsExecuting(false)
        setProcessingPhase('')
        return
      }

      // Phase 2: Generating Query
      setProcessingPhase('generating')
      toast.success('Audio transcribed! Generating SQL query...')
      
      // Phase 3: Executing Query
      setProcessingPhase('executing')
      const executeResponse = await voiceReportsAPI.executeQuery(reportId)

      if (executeResponse.data.success) {
        // Phase 4: Rendering Chart
        setProcessingPhase('rendering')
        await new Promise(resolve => setTimeout(resolve, 500)) // Brief delay for rendering
        
        toast.success(`✅ Chart generated! ${executeResponse.data.row_count} rows visualized`)
        
        setCurrentReport({
          id: reportId,
          transcription: response.data.transcription,
          sql: response.data.sql, // Store but don't show to manager
          intent: response.data.intent,
          status: executeResponse.data.status || 'visualization_created',
          embedUrl: executeResponse.data.embed_url,
          rowCount: executeResponse.data.row_count,
          executionTime: executeResponse.data.execution_time_ms,
          chartType: executeResponse.data.chart_type
        })
        
        setSelectedFile(null)
        loadReports()
      } else {
        toast.error(executeResponse.data.error || 'Chart generation failed')
        setCurrentReport({
          id: reportId,
          transcription: response.data.transcription,
          sql: response.data.sql,
          intent: response.data.intent,
          status: 'failed'
        })
      }
    } catch (error) {
      console.error('Processing error:', error)
      const errorMessage = error.response?.data?.error || error.message || 'Processing failed'
      toast.error(`❌ Error: ${errorMessage}`)
    } finally {
      setIsUploading(false)
      setIsExecuting(false)
      setUploadProgress(0)
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
          chartType: report.chart_type
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

  return (
    <AnimatedPage>
      <div className="space-y-6">
        {/* Header */}
        <motion.div variants={fadeIn}>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
            🎙️ Voice-Driven BI Reports
          </h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">
            Upload audio and get instant AI-powered visualizations. No SQL knowledge required.
          </p>
        </motion.div>

        {/* Upload Section */}
        <motion.div variants={slideInBottom}>
          <Card>
            <h2 className="text-xl font-semibold mb-4 text-gray-900 dark:text-white">
              Upload Audio
            </h2>
            
            <div className="space-y-4">
              {/* File Input */}
              <div className="flex items-center gap-4">
                <label className="flex-1">
                  <div className="flex items-center justify-center w-full h-32 px-4 transition bg-white border-2 border-gray-300 border-dashed rounded-lg appearance-none cursor-pointer hover:border-blue-500 focus:outline-none dark:bg-gray-800 dark:border-gray-600 dark:hover:border-blue-500">
                    <div className="flex flex-col items-center space-y-2">
                      <Upload className="w-8 h-8 text-gray-600 dark:text-gray-400" />
                      <span className="text-sm text-gray-600 dark:text-gray-400">
                        {selectedFile ? selectedFile.name : 'Click to select audio file'}
                      </span>
                      <span className="text-xs text-gray-500">
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

              {/* Upload Progress */}
              {isUploading && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-600 dark:text-gray-400">Uploading...</span>
                    <span className="text-gray-900 dark:text-white font-medium">{uploadProgress}%</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2 dark:bg-gray-700">
                    <div
                      className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                      style={{ width: `${uploadProgress}%` }}
                    />
                  </div>
                </div>
              )}

              {/* Processing Flow Indicator */}
              {processingPhase && (
                <div className="space-y-3 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg border-2 border-blue-200 dark:border-blue-800">
                  <div className="flex items-center gap-3">
                    <Loader className="w-5 h-5 text-blue-600 animate-spin" />
                    <span className="font-semibold text-blue-900 dark:text-blue-100">
                      Processing Your Audio...
                    </span>
                  </div>
                  
                  <div className="flex items-center gap-2">
                    {/* Step 1: Transcribing */}
                    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg flex-1 transition-all ${
                      processingPhase === 'transcribing' 
                        ? 'bg-blue-600 text-white shadow-md' 
                        : processingPhase === 'generating' || processingPhase === 'executing' || processingPhase === 'rendering'
                        ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                        : 'bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-400'
                    }`}>
                      <Mic className="w-4 h-4" />
                      <span className="text-xs font-medium">Transcribing</span>
                    </div>

                    <div className="text-gray-400">→</div>

                    {/* Step 2: Generating Query */}
                    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg flex-1 transition-all ${
                      processingPhase === 'generating' 
                        ? 'bg-blue-600 text-white shadow-md' 
                        : processingPhase === 'executing' || processingPhase === 'rendering'
                        ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                        : 'bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-400'
                    }`}>
                      <Code className="w-4 h-4" />
                      <span className="text-xs font-medium">Generating</span>
                    </div>

                    <div className="text-gray-400">→</div>

                    {/* Step 3: Executing */}
                    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg flex-1 transition-all ${
                      processingPhase === 'executing' 
                        ? 'bg-blue-600 text-white shadow-md' 
                        : processingPhase === 'rendering'
                        ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                        : 'bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-400'
                    }`}>
                      <Database className="w-4 h-4" />
                      <span className="text-xs font-medium">Executing</span>
                    </div>

                    <div className="text-gray-400">→</div>

                    {/* Step 4: Rendering Chart */}
                    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg flex-1 transition-all ${
                      processingPhase === 'rendering' 
                        ? 'bg-blue-600 text-white shadow-md' 
                        : 'bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-400'
                    }`}>
                      <BarChart3 className="w-4 h-4" />
                      <span className="text-xs font-medium">Rendering</span>
                    </div>
                  </div>
                </div>
              )}

              {/* Upload Button */}
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
                    Upload & Process
                  </>
                )}
              </Button>
            </div>
          </Card>
        </motion.div>

        {/* Current Report */}
        {currentReport && (
          <motion.div variants={slideInBottom}>
            <Card>
              <h2 className="text-xl font-semibold mb-4 text-gray-900 dark:text-white flex items-center gap-2">
                <BarChart3 className="w-6 h-6 text-blue-600" />
                Your Generated Chart
              </h2>

              {/* Results */}
              {isReportCompleted(currentReport.status) && (
                <>
                  {/* Metrics */}
                  <div className="grid grid-cols-3 gap-4 mb-6">
                    <div className="p-4 bg-green-50 dark:bg-green-900/20 rounded-lg">
                      <div className="flex items-center gap-2 text-green-600 dark:text-green-400 mb-1">
                        <Database className="w-4 h-4" />
                        <span className="text-sm font-medium">Rows</span>
                      </div>
                      <p className="text-2xl font-bold text-gray-900 dark:text-white">
                        {currentReport.rowCount?.toLocaleString() || 0}
                      </p>
                    </div>

                    <div className="p-4 bg-purple-50 dark:bg-purple-900/20 rounded-lg">
                      <div className="flex items-center gap-2 text-purple-600 dark:text-purple-400 mb-1">
                        <Clock className="w-4 h-4" />
                        <span className="text-sm font-medium">Time</span>
                      </div>
                      <p className="text-2xl font-bold text-gray-900 dark:text-white">
                        {currentReport.executionTime}ms
                      </p>
                    </div>

                    <div className="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
                      <div className="flex items-center gap-2 text-blue-600 dark:text-blue-400 mb-1">
                        <BarChart3 className="w-4 h-4" />
                        <span className="text-sm font-medium">Chart Type</span>
                      </div>
                      <p className="text-2xl font-bold text-gray-900 dark:text-white capitalize">
                        {currentReport.chartType}
                      </p>
                    </div>
                  </div>

                  {/* Embedded Visualization */}
                  {currentReport.embedUrl && (
                    <div className="mb-4">
                      <div className="border-2 border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden shadow-lg">
                        <iframe
                          src={currentReport.embedUrl}
                          width="100%"
                          height="600"
                          frameBorder="0"
                          className="bg-white"
                          title="Data Visualization"
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
                      There was an error processing your audio. Please try again with a different recording.
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
            <h2 className="text-xl font-semibold mb-4 text-gray-900 dark:text-white">
              Your Reports
            </h2>

            {reports.length === 0 ? (
              <div className="text-center py-12">
                <Mic className="w-16 h-16 mx-auto text-gray-400 mb-4" />
                <p className="text-gray-500 dark:text-gray-400">
                  No reports yet. Upload an audio file to get started!
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {reports.map((report) => (
                  <div
                    key={report.id}
                    className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-800 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors cursor-pointer"
                    onClick={() => handleLoadReport(report.id)}
                  >
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-1">
                        <h3 className="font-medium text-gray-900 dark:text-white">
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
                        <p className="text-xs text-gray-500 dark:text-gray-500 mt-1">
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
      </div>
    </AnimatedPage>
  )
}

export default VoiceReportManager


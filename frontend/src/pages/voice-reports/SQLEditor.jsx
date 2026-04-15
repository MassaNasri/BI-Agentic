import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { toast } from 'react-hot-toast'
import { useSearchParams } from 'react-router-dom'
import { 
  Code, 
  Play, 
  Save,
  Database,
  Clock,
  BarChart3,
  CheckCircle,
  AlertCircle,
  Loader
} from 'lucide-react'

import { voiceReportsAPI } from '../../api/endpoints'
import AnimatedPage from '../../components/AnimatedPage'
import Card from '../../components/Card'
import Button from '../../components/Button'
import PreprocessingDetailsPanel from '../../components/preprocessing/PreprocessingDetailsPanel'
import { fadeIn, slideInBottom } from '../../animations/variants'
import {
  isReportCompleted,
  isReportFailed,
  getReportStatusBadgeClass,
  formatReportStatus,
} from '../../utils/reportStatus'

function SQLEditor() {
  const [searchParams] = useSearchParams()
  const selectedReportIdParam = searchParams.get('reportId')
  const [reports, setReports] = useState([])
  const [selectedReport, setSelectedReport] = useState(null)
  const [editedSQL, setEditedSQL] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [isExecuting, setIsExecuting] = useState(false)
  const [hasChanges, setHasChanges] = useState(false)

  useEffect(() => {
    loadReports()
  }, [])

  useEffect(() => {
    if (selectedReport) {
      setEditedSQL(selectedReport.final_sql || selectedReport.generated_sql)
      setHasChanges(false)
    }
  }, [selectedReport])

  const loadReports = async () => {
    try {
      const response = await voiceReportsAPI.listReports()
      if (response.data.success) {
        setReports(response.data.reports || [])
      }
    } catch (error) {
      console.error('Failed to load reports:', error)
      toast.error('Failed to load reports')
    }
  }

  const handleLoadReport = async (reportId) => {
    try {
      const response = await voiceReportsAPI.getReport(reportId)
      
      if (response.data.success) {
        setSelectedReport(response.data.report)
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

  const handleSQLChange = (value) => {
    setEditedSQL(value)
    setHasChanges(value !== (selectedReport?.final_sql || selectedReport?.generated_sql))
  }

  const handleSaveSQL = async () => {
    if (!selectedReport || !editedSQL.trim()) {
      toast.error('Please enter SQL query')
      return
    }

    setIsSaving(true)

    try {
      const response = await voiceReportsAPI.editSQL(selectedReport.id, editedSQL)

      if (response.data.success) {
        toast.success('SQL updated successfully')
        setHasChanges(false)
        
        // Reload report to get updated data
        await handleLoadReport(selectedReport.id)
        await loadReports()
      } else {
        toast.error(response.data.error || 'Failed to update SQL')
      }
    } catch (error) {
      console.error('Save error:', error)
      const errorMessage = error.response?.data?.error || error.message || 'Failed to save SQL'
      toast.error(errorMessage)
    } finally {
      setIsSaving(false)
    }
  }

  const handleExecute = async () => {
    if (!selectedReport) return

    // Save changes first if there are any
    if (hasChanges) {
      await handleSaveSQL()
    }

    setIsExecuting(true)

    try {
      const response = await voiceReportsAPI.executeQuery(selectedReport.id)

      if (response.data.success) {
        toast.success(`Query executed! ${response.data.row_count} rows returned in ${response.data.execution_time_ms}ms`)
        
        // Reload report to get execution results
        await handleLoadReport(selectedReport.id)
        await loadReports()
      } else {
        toast.error(response.data.error || 'Execution failed')
      }
    } catch (error) {
      console.error('Execution error:', error)
      const errorMessage = error.response?.data?.error || error.message || 'Execution failed'
      toast.error(errorMessage)
    } finally {
      setIsExecuting(false)
    }
  }

  return (
    <AnimatedPage>
      <div className="space-y-6">
        {/* Header */}
        <motion.div variants={fadeIn}>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
            📝 SQL Editor
          </h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">
            Edit and optimize SQL queries for voice reports
          </p>
        </motion.div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Reports List */}
          <motion.div variants={slideInBottom} className="lg:col-span-1">
            <Card>
              <h2 className="text-lg font-semibold mb-4 text-gray-900 dark:text-white">
                All Reports
              </h2>

              {reports.length === 0 ? (
                <div className="text-center py-8">
                  <Code className="w-12 h-12 mx-auto text-gray-400 mb-3" />
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    No reports available
                  </p>
                </div>
              ) : (
                <div className="space-y-2 max-h-[600px] overflow-y-auto">
                  {reports.map((report) => (
                    <div
                      key={report.id}
                      onClick={() => handleLoadReport(report.id)}
                      className={`
                        p-3 rounded-lg cursor-pointer transition-colors
                        ${selectedReport?.id === report.id 
                          ? 'bg-blue-100 dark:bg-blue-900/30 border-2 border-blue-500' 
                          : 'bg-gray-50 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700'
                        }
                      `}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-medium text-sm text-gray-900 dark:text-white">
                          Report #{report.id}
                        </span>
                        <span className={`
                          px-2 py-0.5 text-xs rounded-full font-medium
                          ${getReportStatusBadgeClass(report.status)}
                        `}>
                          {formatReportStatus(report.status)}
                        </span>
                      </div>
                      <p className="text-xs text-gray-600 dark:text-gray-400 line-clamp-2">
                        {report.transcription}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </motion.div>

          {/* SQL Editor */}
          <motion.div variants={slideInBottom} className="lg:col-span-2">
            {!selectedReport ? (
              <Card>
                <div className="text-center py-20">
                  <Code className="w-16 h-16 mx-auto text-gray-400 mb-4" />
                  <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
                    No Report Selected
                  </h3>
                  <p className="text-gray-500 dark:text-gray-400">
                    Select a report from the list to edit its SQL query
                  </p>
                </div>
              </Card>
            ) : (
              <div className="space-y-6">
                {/* Report Info */}
                <Card>
                  <div className="flex items-start justify-between mb-4">
                    <div>
                      <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
                        Report #{selectedReport.id}
                      </h2>
                      <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                        {selectedReport.transcription}
                      </p>
                    </div>
                    <span className={`
                      px-3 py-1 text-sm rounded-full font-medium flex items-center gap-1
                      ${getReportStatusBadgeClass(selectedReport.status)}
                    `}>
                      {isReportCompleted(selectedReport.status) && <CheckCircle className="w-4 h-4" />}
                      {isReportFailed(selectedReport.status) && <AlertCircle className="w-4 h-4" />}
                      {formatReportStatus(selectedReport.status)}
                    </span>
                  </div>

                  {/* SQL Editor */}
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
                        SQL Query
                      </label>
                      {hasChanges && (
                        <span className="text-xs text-orange-600 dark:text-orange-400 flex items-center gap-1">
                          <AlertCircle className="w-3 h-3" />
                          Unsaved changes
                        </span>
                      )}
                    </div>
                    
                    <textarea
                      value={editedSQL}
                      onChange={(e) => handleSQLChange(e.target.value)}
                      className="w-full h-64 p-4 bg-gray-900 text-green-400 font-mono text-sm rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="SELECT * FROM table WHERE condition"
                      spellCheck={false}
                    />

                    {/* Action Buttons */}
                    <div className="flex gap-3">
                      <Button
                        onClick={handleSaveSQL}
                        disabled={!hasChanges || isSaving}
                        variant="secondary"
                        className="flex-1"
                      >
                        {isSaving ? (
                          <>
                            <Loader className="w-4 h-4 animate-spin mr-2" />
                            Saving...
                          </>
                        ) : (
                          <>
                            <Save className="w-4 h-4 mr-2" />
                            Save Changes
                          </>
                        )}
                      </Button>

                      <Button
                        onClick={handleExecute}
                        disabled={isExecuting}
                        variant="success"
                        className="flex-1"
                      >
                        {isExecuting ? (
                          <>
                            <Loader className="w-4 h-4 animate-spin mr-2" />
                            Executing...
                          </>
                        ) : (
                          <>
                            <Play className="w-4 h-4 mr-2" />
                            {hasChanges ? 'Save & Execute' : 'Execute'}
                          </>
                        )}
                      </Button>
                    </div>
                  </div>
                </Card>

                <Card>
                  <PreprocessingDetailsPanel
                    preprocessingLow={selectedReport.preprocessing_low}
                    preprocessingHigh={selectedReport.preprocessing_high}
                  />
                </Card>

                {/* Execution Results */}
                {isReportCompleted(selectedReport.status) && selectedReport.row_count && (
                  <Card>
                    <h3 className="text-lg font-semibold mb-4 text-gray-900 dark:text-white">
                      Execution Results
                    </h3>

                    {/* Metrics */}
                    <div className="grid grid-cols-3 gap-4 mb-6">
                      <div className="p-4 bg-green-50 dark:bg-green-900/20 rounded-lg">
                        <div className="flex items-center gap-2 text-green-600 dark:text-green-400 mb-1">
                          <Database className="w-4 h-4" />
                          <span className="text-sm font-medium">Rows</span>
                        </div>
                        <p className="text-2xl font-bold text-gray-900 dark:text-white">
                          {selectedReport.row_count?.toLocaleString() || 0}
                        </p>
                      </div>

                      <div className="p-4 bg-purple-50 dark:bg-purple-900/20 rounded-lg">
                        <div className="flex items-center gap-2 text-purple-600 dark:text-purple-400 mb-1">
                          <Clock className="w-4 h-4" />
                          <span className="text-sm font-medium">Time</span>
                        </div>
                        <p className="text-2xl font-bold text-gray-900 dark:text-white">
                          {selectedReport.execution_time_ms}ms
                        </p>
                      </div>

                      <div className="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
                        <div className="flex items-center gap-2 text-blue-600 dark:text-blue-400 mb-1">
                          <BarChart3 className="w-4 h-4" />
                          <span className="text-sm font-medium">Chart</span>
                        </div>
                        <p className="text-2xl font-bold text-gray-900 dark:text-white capitalize">
                          {selectedReport.chart_type}
                        </p>
                      </div>
                    </div>

                    {/* Embedded Visualization */}
                    {selectedReport.embed_url && (
                      <div>
                        <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                          Visualization
                        </h4>
                        <div className="border-2 border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                          <iframe
                            src={selectedReport.embed_url}
                            width="100%"
                            height="500"
                            frameBorder="0"
                            className="bg-white"
                            title="Data Visualization"
                          />
                        </div>
                      </div>
                    )}
                  </Card>
                )}
              </div>
            )}
          </motion.div>
        </div>
      </div>
    </AnimatedPage>
  )
}

export default SQLEditor


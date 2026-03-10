import { useState, useEffect } from 'react'
import { useAuthStore } from '../../store/auth'
import { BarChart3, Mic, Upload, Loader, AlertCircle, TrendingUp, Database, Clock } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Card, Badge, AnimatedPage } from '../../components'
import { headerTitle, scaleFade } from '../../animations/uiVariants'
import { voiceReportsAPI } from '../../api/endpoints'
import {
  isReportCompleted,
  isReportProcessing,
  getReportStatusBadgeClass,
  formatReportStatus
} from '../../utils/reportStatus'

function Dashboard() {
  const { user } = useAuthStore()
  const navigate = useNavigate()
  const [reports, setReports] = useState([])
  const [stats, setStats] = useState({
    total_reports: 0,
    completed_reports: 0,
    total_rows: 0,
  })
  const [isLoading, setIsLoading] = useState(true)
  const [dashboardUrl, setDashboardUrl] = useState(null)

  useEffect(() => {
    loadDashboardData()
  }, [user?.role])

  const loadDashboardData = async () => {
    setIsLoading(true)
    try {
      let fetchedReports = []

      // Load reports for all roles
      const reportsResponse = await voiceReportsAPI.listReports()
      if (reportsResponse.data.success) {
        fetchedReports = reportsResponse.data.reports || []
        setReports(fetchedReports)
      }

      // Load aggregate stats
      try {
        const statsResponse = await voiceReportsAPI.getDashboardStats()
        if (statsResponse.data.success) {
          setStats({
            total_reports: statsResponse.data.total_reports || 0,
            completed_reports: statsResponse.data.completed_reports || 0,
            total_rows: statsResponse.data.total_rows || 0,
          })
        }
      } catch {
        setStats({
          total_reports: fetchedReports.length,
          completed_reports: fetchedReports.filter((report) => isReportCompleted(report.status)).length,
          total_rows: fetchedReports.reduce((sum, report) => sum + (report.row_count || 0), 0),
        })
      }

      // Load dashboard URL for Executive
      if (user?.role === 'executive') {
        try {
          const dashResponse = await voiceReportsAPI.getWorkspaceDashboard()
          if (dashResponse.data.success) {
            setDashboardUrl(dashResponse.data.dashboard_url)
          }
        } catch (error) {
          console.log('Dashboard not available yet')
        }
      }
    } catch (error) {
      console.error('Failed to load dashboard data:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const openReport = (reportId) => {
    if (user?.role === 'manager') {
      navigate(`/dashboard/voice-reports?reportId=${reportId}`)
      return
    }
    if (user?.role === 'analyst') {
      navigate(`/dashboard/sql-editor?reportId=${reportId}`)
      return
    }
    if (user?.role === 'executive') {
      navigate(`/dashboard/analytics?reportId=${reportId}`)
    }
  }

  // Manager Dashboard - Quick Upload + Recent Charts
  const renderManagerDashboard = () => (
    <>
      {/* Welcome Header */}
      <motion.div 
        variants={headerTitle}
        initial="hidden"
        animate="visible"
        className="bg-gradient-to-r from-blue-600 to-indigo-600 rounded-xl p-8 text-white shadow-lg"
      >
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">
              🎙️ Voice-Driven Analytics
            </h1>
            <p className="text-blue-100 text-lg">
              Upload audio and get instant insights with AI-powered charts
            </p>
          </div>
          <Badge className="bg-white/20 text-white border-white/30">
            {user?.role}
          </Badge>
        </div>
      </motion.div>

      {/* Quick Upload Section */}
      <motion.div variants={scaleFade} initial="hidden" animate="visible">
        <Link to="/dashboard/voice-reports">
          <Card className="hover:shadow-xl transition-all cursor-pointer group border-2 border-blue-100 hover:border-blue-300">
            <div className="flex items-center space-x-6">
              <div className="w-16 h-16 bg-gradient-to-br from-blue-100 to-indigo-100 rounded-xl flex items-center justify-center group-hover:scale-110 transition-transform">
                <Mic className="w-8 h-8 text-blue-600" />
              </div>
              <div className="flex-1">
                <h3 className="text-xl font-bold text-gray-900 mb-1">
                  Create New Voice Report
                </h3>
                <p className="text-gray-600">
                  Upload audio to generate SQL queries and visualizations automatically
                </p>
              </div>
              <Upload className="w-6 h-6 text-gray-400 group-hover:text-blue-600 transition-colors" />
            </div>
          </Card>
        </Link>
      </motion.div>

      {/* Stats */}
      <div className="grid md:grid-cols-3 gap-6">
        <Card>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-blue-100 rounded-lg">
              <BarChart3 className="w-6 h-6 text-blue-600" />
            </div>
            <div>
              <p className="text-sm text-gray-600">Total Reports</p>
              <p className="text-2xl font-bold text-gray-900">{stats.total_reports}</p>
            </div>
          </div>
        </Card>

        <Card>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-green-100 rounded-lg">
              <TrendingUp className="w-6 h-6 text-green-600" />
            </div>
            <div>
              <p className="text-sm text-gray-600">Completed</p>
              <p className="text-2xl font-bold text-gray-900">
                {stats.completed_reports}
              </p>
            </div>
          </div>
        </Card>

        <Card>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-purple-100 rounded-lg">
              <Database className="w-6 h-6 text-purple-600" />
            </div>
            <div>
              <p className="text-sm text-gray-600">Total Rows</p>
              <p className="text-2xl font-bold text-gray-900">
                {(stats.total_rows || 0).toLocaleString()}
              </p>
            </div>
          </div>
        </Card>
      </div>

      {/* Recent Charts */}
      {reports.length > 0 ? (
        <Card>
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-2xl font-bold text-gray-900">Recent Charts</h2>
            <Link to="/dashboard/voice-reports" className="text-blue-600 hover:text-blue-700 text-sm font-medium">
              View All →
            </Link>
          </div>
          
          <div className="grid md:grid-cols-2 gap-6">
            {reports.slice(0, 4).map((report) => (
              <div key={report.id} className="border-2 border-gray-200 rounded-lg overflow-hidden hover:border-blue-300 transition-colors">
                <div className="bg-gray-50 px-4 py-3 border-b">
                  <div className="flex items-center gap-3">
                    <BarChart3 className="w-5 h-5 text-blue-600" />
                    <div className="flex-1">
                      <h3 className="font-semibold text-gray-900 text-sm">Report #{report.id}</h3>
                      <p className="text-xs text-gray-500">
                        {report.row_count?.toLocaleString()} rows • {report.chart_type} chart
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => openReport(report.id)}
                      className="text-xs font-medium text-blue-600 hover:text-blue-700"
                    >
                      Open
                    </button>
                  </div>
                </div>
                {report.embed_url ? (
                  <iframe
                    key={`${report.id}-${report.embed_url}`}
                    src={report.embed_url}
                    width="100%"
                    height="300"
                    frameBorder="0"
                    className="bg-white"
                    title={`Report ${report.id}`}
                  />
                ) : (
                  <div className="h-[300px] flex items-center justify-center bg-gray-50">
                    {isReportProcessing(report.status) || isReportCompleted(report.status) ? (
                      <div className="flex flex-col items-center gap-2 text-gray-500">
                        <Loader className="w-5 h-5 animate-spin" />
                        <p>Visualization is loading...</p>
                      </div>
                    ) : (
                      <p className="text-gray-500">Open this report to view visualization</p>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      ) : (
        <Card>
          <div className="text-center py-12">
            <Mic className="w-16 h-16 mx-auto text-gray-400 mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">No Reports Yet</h3>
            <p className="text-gray-600 mb-6">
              Upload your first audio file to generate insights
            </p>
            <Link to="/dashboard/voice-reports">
              <button className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium">
                Create First Report
              </button>
            </Link>
          </div>
        </Card>
      )}
    </>
  )

  // Analyst Dashboard - Recent Reports with SQL Preview
  const renderAnalystDashboard = () => (
    <>
      {/* Welcome Header */}
      <motion.div 
        variants={headerTitle}
        initial="hidden"
        animate="visible"
        className="bg-gradient-to-r from-purple-600 to-pink-600 rounded-xl p-8 text-white shadow-lg"
      >
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">
              📝 SQL Analysis Hub
            </h1>
            <p className="text-purple-100 text-lg">
              Review and optimize voice-generated SQL queries
            </p>
          </div>
          <Badge className="bg-white/20 text-white border-white/30">
            {user?.role}
          </Badge>
        </div>
      </motion.div>

      {/* Quick Action */}
      <Link to="/dashboard/sql-editor">
        <Card className="hover:shadow-xl transition-all cursor-pointer group border-2 border-purple-100 hover:border-purple-300">
          <div className="flex items-center space-x-6">
            <div className="w-16 h-16 bg-gradient-to-br from-purple-100 to-pink-100 rounded-xl flex items-center justify-center group-hover:scale-110 transition-transform">
              <BarChart3 className="w-8 h-8 text-purple-600" />
            </div>
            <div className="flex-1">
              <h3 className="text-xl font-bold text-gray-900 mb-1">
                Open SQL Editor
              </h3>
              <p className="text-gray-600">
                Edit, optimize, and execute SQL queries for all workspace reports
              </p>
            </div>
          </div>
        </Card>
      </Link>

      {/* Stats */}
      <div className="grid md:grid-cols-3 gap-6">
        <Card>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-blue-100 rounded-lg">
              <BarChart3 className="w-6 h-6 text-blue-600" />
            </div>
            <div>
              <p className="text-sm text-gray-600">Total Reports</p>
              <p className="text-2xl font-bold text-gray-900">{stats.total_reports}</p>
            </div>
          </div>
        </Card>

        <Card>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-purple-100 rounded-lg">
              <Clock className="w-6 h-6 text-purple-600" />
            </div>
            <div>
              <p className="text-sm text-gray-600">Avg. Query Time</p>
              <p className="text-2xl font-bold text-gray-900">
                {reports.length > 0 
                  ? Math.round(reports.reduce((sum, r) => sum + (r.execution_time_ms || 0), 0) / reports.length)
                  : 0}ms
              </p>
            </div>
          </div>
        </Card>

        <Card>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-green-100 rounded-lg">
              <Database className="w-6 h-6 text-green-600" />
            </div>
            <div>
              <p className="text-sm text-gray-600">Total Rows</p>
              <p className="text-2xl font-bold text-gray-900">
                {(stats.total_rows || 0).toLocaleString()}
              </p>
            </div>
          </div>
        </Card>
      </div>

      {/* Recent Reports */}
      {reports.length > 0 ? (
        <Card>
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-2xl font-bold text-gray-900">Recent Reports</h2>
            <Link to="/dashboard/sql-editor" className="text-purple-600 hover:text-purple-700 text-sm font-medium">
              View All →
            </Link>
          </div>
          
          <div className="space-y-4">
            {reports.slice(0, 5).map((report) => (
              <div
                key={report.id}
                className="p-4 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors cursor-pointer"
                onClick={() => openReport(report.id)}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-3">
                    <span className="font-semibold text-gray-900">Report #{report.id}</span>
                    <span className={`px-2 py-1 text-xs rounded-full ${getReportStatusBadgeClass(report.status)}`}>
                      {formatReportStatus(report.status)}
                    </span>
                  </div>
                  <div className="text-sm text-gray-500">
                    {report.row_count?.toLocaleString()} rows • {report.execution_time_ms}ms
                  </div>
                </div>
                <p className="text-sm text-gray-600 mb-2">{report.transcription}</p>
                {report.sql && (
                  <div className="p-3 bg-gray-800 rounded text-xs text-green-400 font-mono overflow-x-auto">
                    {report.sql}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      ) : (
        <Card>
          <div className="text-center py-12">
            <AlertCircle className="w-16 h-16 mx-auto text-gray-400 mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">No Reports Available</h3>
            <p className="text-gray-600">
              Waiting for managers to create voice reports
            </p>
          </div>
        </Card>
      )}
    </>
  )

  // Executive Dashboard - Full Dashboard View
  const renderExecutiveDashboard = () => (
    <>
      {/* Welcome Header */}
      <motion.div 
        variants={headerTitle}
        initial="hidden"
        animate="visible"
        className="bg-gradient-to-r from-green-600 to-teal-600 rounded-xl p-8 text-white shadow-lg"
      >
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">
              📊 Executive Dashboard
            </h1>
            <p className="text-green-100 text-lg">
              Comprehensive analytics and insights at a glance
            </p>
          </div>
          <Badge className="bg-white/20 text-white border-white/30">
            {user?.role}
          </Badge>
        </div>
      </motion.div>

      {/* Stats */}
      <div className="grid md:grid-cols-3 gap-6">
        <Card>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-blue-100 rounded-lg">
              <BarChart3 className="w-6 h-6 text-blue-600" />
            </div>
            <div>
              <p className="text-sm text-gray-600">Total Reports</p>
              <p className="text-2xl font-bold text-gray-900">{stats.total_reports}</p>
            </div>
          </div>
        </Card>

        <Card>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-green-100 rounded-lg">
              <TrendingUp className="w-6 h-6 text-green-600" />
            </div>
            <div>
              <p className="text-sm text-gray-600">Completed</p>
              <p className="text-2xl font-bold text-gray-900">
                {stats.completed_reports}
              </p>
            </div>
          </div>
        </Card>

        <Card>
          <div className="flex items-center gap-4">
            <div className="p-3 bg-purple-100 rounded-lg">
              <Database className="w-6 h-6 text-purple-600" />
            </div>
            <div>
              <p className="text-sm text-gray-600">Total Rows</p>
              <p className="text-2xl font-bold text-gray-900">
                {(stats.total_rows || 0).toLocaleString()}
              </p>
            </div>
          </div>
        </Card>
      </div>

      {/* Workspace Dashboard */}
      {isLoading ? (
        <Card>
          <div className="flex flex-col items-center justify-center py-20">
            <Loader className="w-12 h-12 text-blue-600 animate-spin mb-4" />
            <p className="text-gray-600">Loading dashboard...</p>
          </div>
        </Card>
      ) : dashboardUrl ? (
        <Card>
          <div className="mb-4">
            <h2 className="text-2xl font-bold text-gray-900">Workspace Analytics</h2>
            <p className="text-gray-600">Comprehensive view of all voice-generated insights</p>
          </div>
          <div className="border-2 border-gray-200 rounded-lg overflow-hidden">
            <iframe
              key={dashboardUrl}
              src={dashboardUrl}
              width="100%"
              height="800"
              frameBorder="0"
              className="bg-white"
              title="Analytics Dashboard"
            />
          </div>
        </Card>
      ) : (
        <Card>
          <div className="text-center py-20">
            <AlertCircle className="w-16 h-16 mx-auto text-yellow-500 mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">
              Dashboard Not Available
            </h3>
            <p className="text-gray-600 mb-6">
              No dashboard available yet. Reports need to be created first.
            </p>
            <Link to="/dashboard/analytics">
              <button className="px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors font-medium">
                View Analytics Page
              </button>
            </Link>
          </div>
        </Card>
      )}
    </>
  )

  return (
    <AnimatedPage className="max-w-7xl mx-auto space-y-6">
      {user?.role === 'manager' && renderManagerDashboard()}
      {user?.role === 'analyst' && renderAnalystDashboard()}
      {user?.role === 'executive' && renderExecutiveDashboard()}
    </AnimatedPage>
  )
}

export default Dashboard


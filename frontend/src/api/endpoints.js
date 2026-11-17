import apiClient from './axios'

// ============================================================================
// Authentication Endpoints
// ============================================================================

export const authAPI = {
  // R1: Sign Up
  signup: (data) => apiClient.post('/auth/signup/', data),
  
  // R2: Email Verification
  verifyEmail: (token) => apiClient.get(`/auth/verify-email/?token=${token}`),
  
  // R3: Login
  login: (credentials) => apiClient.post('/auth/login/', credentials),
  
  // R4: Logout
  logout: (refreshToken) => apiClient.post('/auth/logout/', { refresh: refreshToken }),

  // Forgot password flow
  requestPasswordResetCode: (email) => apiClient.post('/auth/forgot-password/request/', { email }),
  verifyPasswordResetCode: (email, code) => apiClient.post('/auth/forgot-password/verify/', { email, code }),
  resetPassword: (resetToken, newPassword, confirmNewPassword) =>
    apiClient.post('/auth/forgot-password/reset/', {
      reset_token: resetToken,
      new_password: newPassword,
      confirm_new_password: confirmNewPassword,
    }),
  
  // Token refresh
  refreshToken: (refresh) => apiClient.post('/auth/token/refresh/', { refresh }),
}

// ============================================================================
// User Profile Endpoints
// ============================================================================

export const userAPI = {
  // R5: View Profile
  getProfile: () => apiClient.get('/user/profile/'),
  
  // R6: Update Profile
  updateProfile: (data) => apiClient.put('/user/profile/', data),

  // Change password
  changePassword: (data) => apiClient.post('/user/change-password/', data),
  
  // R6: Deactivate Account
  deactivateAccount: (refreshToken) => apiClient.delete('/user/deactivate/', { data: { refresh: refreshToken } }),
}

// ============================================================================
// Workspace Endpoints
// ============================================================================

export const workspaceAPI = {
  // Get workspace info
  getWorkspace: () => apiClient.get('/workspace/'),

  // R7: Update Workspace Info
  updateWorkspace: (data) => apiClient.put('/workspace/', data),
  
  // R8: View Workspace Members
  getMembers: () => apiClient.get('/workspace/members/'),
  
  // R9: Invite Members
  inviteMember: (data) => apiClient.post('/workspace/invite/', data),
  
  // Remove Pending Invitation
  removeInvitation: (email) => apiClient.delete(`/workspace/invitation/${encodeURIComponent(email)}/`),
  
  // R10: Assign Role
  assignRole: (memberId, role) => apiClient.put(`/workspace/member/${memberId}/role/`, { role }),
  
  // R11: View Member
  getMember: (memberId) => apiClient.get(`/workspace/member/${memberId}/`),
  
  // R11: Update Member
  updateMember: (memberId, data) => apiClient.put(`/workspace/member/${memberId}/`, data),
  
  // R11: Remove Member
  removeMember: (memberId) => apiClient.delete(`/workspace/member/${memberId}/`),
  
  // R12: Suspend Member
  suspendMember: (memberId) => apiClient.put(`/workspace/member/${memberId}/suspend/`),
  
  // Unsuspend Member
  unsuspendMember: (memberId) => apiClient.put(`/workspace/member/${memberId}/unsuspend/`),
  
  // R13: Accept Invitation
  acceptInvitation: (token) => apiClient.get(`/workspace/accept-invite/?token=${token}`),
}

// ============================================================================
// Database Endpoints (Manager Only)
// ============================================================================

export const databaseAPI = {
  listSources: () => apiClient.get('/database/sources/'),
  createSource: (source) => apiClient.post('/database/sources/', source),
  updateSource: (sourceId, changes) => apiClient.patch(`/database/sources/${sourceId}/`, changes),
  retireSource: (sourceId) => apiClient.delete(`/database/sources/${sourceId}/`),
  configureSourceCredential: (sourceId, password) => apiClient.post(`/database/sources/${sourceId}/credential/configure/`, { password }),
  rotateSourceCredential: (sourceId, password) => apiClient.post(`/database/sources/${sourceId}/credential/rotate/`, { password }),
  revokeSourceCredential: (sourceId) => apiClient.post(`/database/sources/${sourceId}/credential/revoke/`, {}),
  listDatasets: () => apiClient.get('/database/datasets/'),
  getSourceCapabilities: () => apiClient.get('/database/sources/capabilities/'),
  testSourceConnection: (sourceId) =>
    apiClient.post('/database/sources/test/', { source_id: sourceId }),
  discoverSource: (sourceId, schema = null, table = null) =>
    apiClient.post('/database/sources/discover/', { source_id: sourceId, schema, table }),
  startSnapshot: (engine, configuration, tables, chunkSize = 1000, sourceId = null, name = null) =>
    apiClient.post('/database/sources/snapshot/', {
      engine,
      configuration: engine === 'sqlite' ? configuration : {},
      tables,
      chunk_size: chunkSize,
      ...(sourceId ? { source_id: sourceId } : {}),
      ...(name ? { name } : {}),
    }),
  prepareSQLite: (file, onUploadProgress) => {
    const formData = new FormData()
    formData.append('file', file)
    return apiClient.post('/database/sources/sqlite/prepare/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress,
    })
  },
  // Upload database file
  uploadDatabase: (file, onUploadProgress) => {
    const formData = new FormData()
    formData.append('file', file)
    
    return apiClient.post('/database/upload/', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress,
    })
  },
  
  // Get manager's database information
  getDatabaseInfo: (datasetId = null) => apiClient.get('/database/', {
    params: datasetId ? { dataset_id: datasetId } : {},
  }),
  
  // Get database preview (first 5 rows)
  getDatabasePreview: (tableId = null, datasetId = null) => apiClient.get('/database/preview/', {
    params: { ...(tableId ? { table: tableId } : {}), ...(datasetId ? { dataset_id: datasetId } : {}) },
  }),
  getDatabaseSchema: (tableId = null, datasetId = null) => apiClient.get('/database/schema/', {
    params: { ...(tableId ? { table: tableId } : {}), ...(datasetId ? { dataset_id: datasetId } : {}) },
  }),
  
  // Delete manager's database
  deleteDatabase: (datasetId = null) => apiClient.delete('/database/', {
    params: datasetId ? { dataset_id: datasetId } : {},
  }),
}

// ============================================================================
// Voice Reports Endpoints
// ============================================================================

export const voiceReportsAPI = {
  // Health check
  healthCheck: () => apiClient.get('/voice-reports/health/'),
  
  // Upload audio file (Manager)
  uploadAudio: (audioFile, onUploadProgress) => {
    const formData = new FormData()
    formData.append('audio', audioFile)
    
    return apiClient.post('/voice-reports/upload/', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress,
    })
  },

  // Submit text query directly to AI pipeline (skip Whisper)
  submitTextQuery: (text, workspaceId) =>
    apiClient.post('/voice-reports/text-query/', {
      text,
      workspace_id: workspaceId,
    }),
  
  // Execute SQL query (Manager/Analyst)
  executeQuery: (reportId) => apiClient.post(`/voice-reports/${reportId}/execute/`),
  
  // Edit SQL query (Analyst only)
  editSQL: (reportId, sql) => apiClient.put(`/voice-reports/${reportId}/sql/`, { sql }),
  
  // List all reports
  listReports: (params = {}) => apiClient.get('/voice-reports/reports/', { params }),
  
  // Get report details
  getReport: (reportId) => apiClient.get(`/voice-reports/${reportId}/`),

  // Get normalized AI explainability trace
  getAITrace: (reportId) => apiClient.get(`/voice-reports/${reportId}/ai-trace/`),

  // Chart type capabilities and manual chart switching
  getReportChartTypeCapabilities: (reportId) =>
    apiClient.get(`/voice-reports/${reportId}/chart-types/capabilities/`),
  switchReportChartType: (reportId, chartType) =>
    apiClient.post(`/voice-reports/${reportId}/chart-types/switch/`, { chart_type: chartType }),
  
  // Delete report (Manager only)
  deleteReport: (reportId) => apiClient.delete(`/voice-reports/${reportId}/`),
  
  // Get workspace dashboard (Executive)
  getWorkspaceDashboard: () => apiClient.get('/voice-reports/dashboard/'),

  // Dashboard aggregate counters
  getDashboardStats: () => apiClient.get('/voice-reports/dashboard/stats/'),

  // Dashboard builder pages/widgets (Phase 1 foundation)
  listDashboardPages: (params = {}) => apiClient.get('/voice-reports/pages/', { params }),
  getDashboardPage: (pageId) => apiClient.get(`/voice-reports/pages/${pageId}/`),
  createDashboardPage: (data) => apiClient.post('/voice-reports/pages/', data),
  updateDashboardPage: (pageId, data) => apiClient.patch(`/voice-reports/pages/${pageId}/`, data),
  deleteDashboardPage: (pageId) => apiClient.delete(`/voice-reports/pages/${pageId}/`),
  listDashboardPageWidgets: (pageId, params = {}) =>
    apiClient.get(`/voice-reports/pages/${pageId}/widgets/`, { params }),
  createDashboardWidget: (pageId, data) =>
    apiClient.post(`/voice-reports/pages/${pageId}/widgets/`, data),
  updateDashboardWidget: (widgetId, data) =>
    apiClient.patch(`/voice-reports/widgets/${widgetId}/`, data),
  deleteDashboardWidget: (widgetId) =>
    apiClient.delete(`/voice-reports/widgets/${widgetId}/`),
  batchUpdateDashboardWidgets: (data) =>
    apiClient.post('/voice-reports/widgets/batch-layout/', data),
}

// ============================================================================
// Subscription Endpoints
// ============================================================================

export const subscriptionAPI = {
  listPlans: () => apiClient.get('/subscription/plans/'),
  getCurrentSubscription: (workspaceId) =>
    apiClient.get('/subscription/current/', { params: { workspace_id: workspaceId } }),
  checkAccess: (workspaceId, consume = false) =>
    apiClient.get('/subscription/check-access/', {
      params: { workspace_id: workspaceId, consume },
    }),
  subscribe: (data) => apiClient.post('/subscription/subscribe/', data),
}

// ============================================================================
// Admin Endpoints
// ============================================================================

export const adminAPI = {
  listPlans: () => apiClient.get('/admin/plans/'),
  createPlan: (data) => apiClient.post('/admin/plans/', data),
  updatePlan: (planId, data) => apiClient.patch(`/admin/plans/${planId}/`, data),
  deletePlan: (planId) => apiClient.delete(`/admin/plans/${planId}/`),
  listUsers: () => apiClient.get('/admin/users/'),
  listWorkspaces: () => apiClient.get('/admin/workspaces/'),
  getStats: () => apiClient.get('/admin/stats/'),
}

export default {
  auth: authAPI,
  user: userAPI,
  workspace: workspaceAPI,
  database: databaseAPI,
  voiceReports: voiceReportsAPI,
  subscription: subscriptionAPI,
  admin: adminAPI,
}


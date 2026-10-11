# API inventory

171 static route declarations, including include mounts and duplicate/legacy URL modules; this is not a count of reachable endpoints. Resolve root URLConf and gateway routing together. No first-party canonical OpenAPI document was found. Request/response validation is distributed across serializers, Pydantic DTOs and manual request.data extraction; full generated schemas and live behavior are NOT VERIFIED for every route.

Core DRF defaults generally require bearer authentication; auth public routes explicitly AllowAny, notification validates its internal key manually despite AllowAny, AI uses require_internal_api_key decorators, ETL DRF defaults are public. Route-specific object authorization remains necessary (SEC-001/002/005).

| URL module | Line | Declaration |
| --- | --- | --- |
| etl-final/connector-service/connector/connector/urls.py | 21 | path('admin/', admin.site.urls) |
| etl-final/connector-service/connector/connector/urls.py | 22 | path('api/', include('etl_engine.urls')) |
| etl-final/connector-service/connector/etl_engine/urls.py | 5 | path('upload/', UploadFileView.as_view()) |
| etl-final/connector-service/connector/etl_engine/urls.py | 6 | path('connect-db/', ConnectDBView.as_view()) |
| etl-final/connector-service/connector/etl_engine/urls.py | 7 | path('health/', HealthView.as_view()) |
| etl-final/connector-service/connector/etl_engine/urls.py | 8 | path('metrics/', MetricsView.as_view()) |
| etl-final/detector-service/detector/core/urls.py | 5 | path('run-detector/', RunDetectorView.as_view(), name='run-detector') |
| etl-final/detector-service/detector/core/urls.py | 6 | path('health/', HealthView.as_view()) |
| etl-final/detector-service/detector/core/urls.py | 7 | path('metrics/', MetricsView.as_view()) |
| etl-final/detector-service/detector/detector/urls.py | 21 | path('admin/', admin.site.urls) |
| etl-final/detector-service/detector/detector/urls.py | 22 | path('api/', include('core.urls')) |
| etl-final/extractor-service/extractor/engine/urls.py | 5 | path('run/', RunExtractorView.as_view()) |
| etl-final/extractor-service/extractor/engine/urls.py | 6 | path('progress/<str:extraction_id>/', ExtractionProgressView.as_view()) |
| etl-final/extractor-service/extractor/engine/urls.py | 7 | path('progress/', ExtractionProgressView.as_view()) |
| etl-final/extractor-service/extractor/engine/urls.py | 8 | path('health/', HealthView.as_view()) |
| etl-final/extractor-service/extractor/engine/urls.py | 9 | path('metrics/', MetricsView.as_view()) |
| etl-final/extractor-service/extractor/extractor/urls.py | 21 | path('admin/', admin.site.urls) |
| etl-final/extractor-service/extractor/extractor/urls.py | 22 | path('api/', include('engine.urls')) |
| etl-final/loader-service/loader/engine/urls.py | 5 | path('test/', TestLoaderView.as_view()) |
| etl-final/loader-service/loader/loader/urls.py | 21 | path('admin/', admin.site.urls) |
| etl-final/loader-service/loader/loader/urls.py | 22 | path('api/', include('engine.urls')) |
| etl-final/metadata-service/metadata/api/urls.py | 15 | path('logs/connections/', ConnectionLogsView.as_view()) |
| etl-final/metadata-service/metadata/api/urls.py | 16 | path('logs/schema/', SchemaLogsView.as_view()) |
| etl-final/metadata-service/metadata/api/urls.py | 17 | path('logs/extract/', ExtractLogsView.as_view()) |
| etl-final/metadata-service/metadata/api/urls.py | 18 | path('logs/transform/', TransformLogsView.as_view()) |
| etl-final/metadata-service/metadata/api/urls.py | 19 | path('logs/load/', LoadLogsView.as_view()) |
| etl-final/metadata-service/metadata/api/urls.py | 20 | path('lineage/<str:row_id>/', LineageQueryView.as_view()) |
| etl-final/metadata-service/metadata/api/urls.py | 21 | path('quality/trends/', QualityTrendsView.as_view()) |
| etl-final/metadata-service/metadata/api/urls.py | 22 | path('health/', HealthView.as_view()) |
| etl-final/metadata-service/metadata/api/urls.py | 23 | path('metrics/', MetricsView.as_view()) |
| etl-final/metadata-service/metadata/metadata/urls.py | 21 | path('admin/', admin.site.urls) |
| etl-final/metadata-service/metadata/metadata/urls.py | 22 | path('api/', include('api.urls')) |
| etl-final/transformer-service/transformer/engine/urls.py | 5 | path('test/', TestTransformView.as_view()) |
| etl-final/transformer-service/transformer/engine/urls.py | 6 | path('quarantine/', QuarantineReviewView.as_view()) |
| etl-final/transformer-service/transformer/engine/urls.py | 7 | path('quarantine/reprocess/', QuarantineReprocessView.as_view()) |
| etl-final/transformer-service/transformer/engine/urls.py | 8 | path('health/', HealthView.as_view()) |
| etl-final/transformer-service/transformer/engine/urls.py | 9 | path('metrics/', MetricsView.as_view()) |
| etl-final/transformer-service/transformer/transformer/urls.py | 21 | path('admin/', admin.site.urls) |
| etl-final/transformer-service/transformer/transformer/urls.py | 22 | path('api/', include('engine.urls')) |
| services/ai-service/backend/urls.py | 26 | path('admin/', admin.site.urls) |
| services/ai-service/backend/urls.py | 27 | path('health/', health_view) |
| services/ai-service/backend/urls.py | 28 | path('api/', include('whisper_app.urls')) |
| services/ai-service/backend/urls.py | 29 | path('api/reasoning/', include('reasoning_app.urls')) |
| services/ai-service/backend/urls.py | 30 | path('api/llm/', include('llm_app.urls')) |
| services/ai-service/llm_app/urls.py | 5 | path('intent/', intent_test_view, name='intent_test') |
| services/ai-service/llm_app/urls.py | 6 | path('forecasting/detect/', forecast_detect_view, name='forecast_detect') |
| services/ai-service/llm_app/urls.py | 7 | path('forecasting/dataset/', forecast_dataset_view, name='forecast_dataset') |
| services/ai-service/reasoning_app/urls.py | 5 | path('test/', reasoning_test_view, name='reasoning_test') |
| services/ai-service/whisper_app/urls.py | 5 | path('transcribe/', transcribe_view, name='transcribe') |
| services/api-gateway/service_config/urls.py | 6 | path('health/', HealthView.as_view(), name='gateway-health') |
| services/api-gateway/service_config/urls.py | 7 | re_path('^.*$', ProxyView.as_view(), name='gateway-proxy') |
| services/auth-service/service_config/urls.py | 9 | path('admin/users/', AdminUsersView.as_view(), name='admin-users') |
| services/auth-service/service_config/urls.py | 10 | path('admin/users/<int:user_id>/', AdminUserDetailView.as_view(), name='admin-user-detail') |
| services/auth-service/service_config/urls.py | 11 | path('admin/', admin.site.urls) |
| services/auth-service/service_config/urls.py | 12 | path('auth/', include('users.auth_urls')) |
| services/auth-service/service_config/urls.py | 13 | path('user/', include('users.user_urls')) |
| services/auth-service/service_config/urls.py | 14 | path('internal/', include('users.internal_urls')) |
| services/auth-service/users/auth_urls.py | 17 | path('signup/', SignUpView.as_view(), name='signup') |
| services/auth-service/users/auth_urls.py | 18 | path('verify-email/', EmailVerificationView.as_view(), name='verify-email') |
| services/auth-service/users/auth_urls.py | 19 | path('login/', LoginView.as_view(), name='login') |
| services/auth-service/users/auth_urls.py | 20 | path('logout/', LogoutView.as_view(), name='logout') |
| services/auth-service/users/auth_urls.py | 21 | path("[REDACTED]", ForgotPasswordRequestView.as_view(), name=[REDACTED] |
| services/auth-service/users/auth_urls.py | 22 | path("[REDACTED]", ForgotPasswordVerifyView.as_view(), name=[REDACTED] |
| services/auth-service/users/auth_urls.py | 23 | path("[REDACTED]", ForgotPasswordResetView.as_view(), name=[REDACTED] |
| services/auth-service/users/auth_urls.py | 24 | path("[REDACTED]", TokenRefreshView.as_view(), name=[REDACTED] |
| services/auth-service/users/internal_urls.py | 8 | path('users/by-email/', InternalUserByEmailView.as_view(), name='internal-user-by-email') |
| services/auth-service/users/internal_urls.py | 9 | path('users/<int:user_id>/', InternalUserDetailView.as_view(), name='internal-user-detail') |
| services/auth-service/users/user_urls.py | 8 | path('profile/', ProfileView.as_view(), name='profile') |
| services/auth-service/users/user_urls.py | 9 | path("[REDACTED]", ChangePasswordView.as_view(), name=[REDACTED] |
| services/auth-service/users/user_urls.py | 10 | path('deactivate/', DeactivateAccountView.as_view(), name='deactivate-account') |
| services/notification-service/notification/urls.py | 10 | path('notification/health/', NotificationHealthView.as_view(), name='notification-health') |
| services/notification-service/notification/urls.py | 11 | path('notification/events/', NotificationEventView.as_view(), name='notification-events') |
| services/notification-service/notification/urls.py | 12 | path('notification/subscriptions/expiry-warnings/run/', SubscriptionExpiryWarningRunView.as_view(), name='notification-subscription-expiry-warnings-run') |
| services/notification-service/service_config/urls.py | 7 | path('', include('notification.urls')) |
| services/notification-service/service_config/urls.py | 8 | path('admin/', admin.site.urls) |
| services/query-service/database/urls.py | 12 | path('health/', DatabaseHealthCheckView.as_view(), name='database-health') |
| services/query-service/database/urls.py | 15 | path('upload/', DatabaseUploadView.as_view(), name='database-upload') |
| services/query-service/database/urls.py | 16 | path('', DatabaseDetailView.as_view(), name='database-detail') |
| services/query-service/database/urls.py | 17 | path('preview/', DatabasePreviewView.as_view(), name='database-preview') |
| services/query-service/database/urls.py | 18 | path('<int:database_id>/status/', DatabaseStatusView.as_view(), name='database-status') |
| services/query-service/query_api/urls.py | 6 | path('health/', QueryHealthView.as_view(), name='query-health') |
| services/query-service/query_api/urls.py | 7 | path('validate/', QueryValidateInternalView.as_view(), name='query-validate') |
| services/query-service/query_api/urls.py | 8 | path('execute/', QueryExecuteInternalView.as_view(), name='query-execute') |
| services/query-service/service_config/urls.py | 7 | path('admin/', admin.site.urls) |
| services/query-service/service_config/urls.py | 8 | path('database/', include('database.urls')) |
| services/query-service/service_config/urls.py | 9 | path('query/', include('query_api.urls')) |
| services/report-service/service_config/urls.py | 7 | path('admin/', admin.site.urls) |
| services/report-service/service_config/urls.py | 8 | path('voice-reports/', include('voice_reports.report_urls')) |
| services/report-service/voice_reports/report_urls.py | 6 | path('health/', views.HealthCheckView.as_view(), name='voice-reports-health') |
| services/report-service/voice_reports/report_urls.py | 7 | path('dashboard/', views.WorkspaceDashboardView.as_view(), name='workspace-dashboard') |
| services/report-service/voice_reports/report_urls.py | 8 | path('dashboard/stats/', views.DashboardStatsView.as_view(), name='dashboard-stats') |
| services/report-service/voice_reports/report_urls.py | 9 | path('reports/', views.ReportListView.as_view(), name='report-list') |
| services/report-service/voice_reports/report_urls.py | 10 | path('pages/', views.DashboardPageListCreateView.as_view(), name='dashboard-page-list-create') |
| services/report-service/voice_reports/report_urls.py | 11 | path('pages/reorder/', views.DashboardPageReorderView.as_view(), name='dashboard-page-reorder') |
| services/report-service/voice_reports/report_urls.py | 12 | path('pages/<int:page_id>/', views.DashboardPageDetailView.as_view(), name='dashboard-page-detail') |
| services/report-service/voice_reports/report_urls.py | 13 | path('pages/<int:page_id>/widgets/', views.DashboardPageWidgetListCreateView.as_view(), name='dashboard-page-widgets') |
| services/report-service/voice_reports/report_urls.py | 14 | path('widgets/batch-layout/', views.DashboardWidgetBatchUpdateView.as_view(), name='dashboard-widget-batch-update') |
| services/report-service/voice_reports/report_urls.py | 15 | path('widgets/<int:widget_id>/', views.DashboardWidgetDetailView.as_view(), name='dashboard-widget-detail') |
| services/report-service/voice_reports/report_urls.py | 16 | path('<int:report_id>/sql/', views.SQLEditView.as_view(), name='sql-edit') |
| services/report-service/voice_reports/report_urls.py | 17 | path('<int:report_id>/ai-trace/', views.AITraceDetailView.as_view(), name='report-ai-trace') |
| services/report-service/voice_reports/report_urls.py | 18 | path('<int:report_id>/chart-types/capabilities/', views.ReportChartTypeCapabilitiesView.as_view(), name='report-chart-type-capabilities') |
| services/report-service/voice_reports/report_urls.py | 19 | path('<int:report_id>/chart-types/switch/', views.ReportChartTypeSwitchView.as_view(), name='report-chart-type-switch') |
| services/report-service/voice_reports/report_urls.py | 20 | path('<int:report_id>/', views.ReportDetailView.as_view(), name='report-detail') |
| services/report-service/voice_reports/urls.py | 12 | path('health/', views.HealthCheckView.as_view(), name='voice-reports-health') |
| services/report-service/voice_reports/urls.py | 15 | path('upload/', views.VoiceUploadView.as_view(), name='voice-upload') |
| services/report-service/voice_reports/urls.py | 18 | path('<int:report_id>/execute/', views.QueryExecuteView.as_view(), name='query-execute') |
| services/report-service/voice_reports/urls.py | 21 | path('<int:report_id>/sql/', views.SQLEditView.as_view(), name='sql-edit') |
| services/report-service/voice_reports/urls.py | 24 | path('reports/', views.ReportListView.as_view(), name='report-list') |
| services/report-service/voice_reports/urls.py | 25 | path('<int:report_id>/', views.ReportDetailView.as_view(), name='report-detail') |
| services/report-service/voice_reports/urls.py | 28 | path('dashboard/stats/', views.DashboardStatsView.as_view(), name='dashboard-stats') |
| services/report-service/voice_reports/urls.py | 29 | path('dashboard/', views.WorkspaceDashboardView.as_view(), name='workspace-dashboard') |
| services/subscription-service/service_config/urls.py | 7 | path('', include('subscription.urls')) |
| services/subscription-service/service_config/urls.py | 8 | path('admin/', admin.site.urls) |
| services/subscription-service/subscription/urls.py | 15 | path('check-access/', CheckAccessView.as_view(), name='subscription-check-access-legacy') |
| services/subscription-service/subscription/urls.py | 16 | path('subscribe/', SubscribeView.as_view(), name='subscription-subscribe-legacy') |
| services/subscription-service/subscription/urls.py | 17 | path('plans/', PlanCatalogView.as_view(), name='subscription-plan-catalog-legacy') |
| services/subscription-service/subscription/urls.py | 18 | path('subscription/health/', HealthView.as_view(), name='subscription-health') |
| services/subscription-service/subscription/urls.py | 19 | path('subscription/plans/', PlanCatalogView.as_view(), name='subscription-plan-catalog') |
| services/subscription-service/subscription/urls.py | 20 | path('subscription/subscribe/', SubscribeView.as_view(), name='subscription-subscribe') |
| services/subscription-service/subscription/urls.py | 21 | path('subscription/current/', CurrentSubscriptionView.as_view(), name='subscription-current') |
| services/subscription-service/subscription/urls.py | 22 | path('subscription/check-access/', CheckAccessView.as_view(), name='subscription-check-access') |
| services/subscription-service/subscription/urls.py | 23 | path('admin/plans/', AdminPlanListCreateView.as_view(), name='admin-plan-list-create') |
| services/subscription-service/subscription/urls.py | 24 | path('admin/plans/<int:plan_id>/', AdminPlanDetailView.as_view(), name='admin-plan-detail') |
| services/subscription-service/subscription/urls.py | 25 | path('admin/stats/', AdminStatsView.as_view(), name='admin-stats') |
| services/visualization-service/service_config/urls.py | 7 | path('admin/', admin.site.urls) |
| services/visualization-service/service_config/urls.py | 8 | path('visualization/', include('visualization_api.urls')) |
| services/visualization-service/visualization_api/urls.py | 13 | path('health/', VisualizationHealthView.as_view(), name='visualization-health') |
| services/visualization-service/visualization_api/urls.py | 14 | path('question/create/', CreateQuestionView.as_view(), name='create-question') |
| services/visualization-service/visualization_api/urls.py | 15 | path('dashboard/create/', CreateDashboardView.as_view(), name='create-dashboard') |
| services/visualization-service/visualization_api/urls.py | 16 | path('dashboard/add-question/', AddQuestionToDashboardView.as_view(), name='add-question-to-dashboard') |
| services/visualization-service/visualization_api/urls.py | 17 | path('question/<int:question_id>/embed-url/', QuestionEmbedUrlView.as_view(), name='question-embed-url') |
| services/visualization-service/visualization_api/urls.py | 18 | path('dashboard/<int:dashboard_id>/embed-url/', DashboardEmbedUrlView.as_view(), name='dashboard-embed-url') |
| services/voice-service/service_config/urls.py | 7 | path('admin/', admin.site.urls) |
| services/voice-service/service_config/urls.py | 8 | path('voice-reports/', include('voice_reports.urls')) |
| services/voice-service/voice_reports/urls.py | 13 | path('health/', views.HealthCheckView.as_view(), name='voice-reports-health') |
| services/voice-service/voice_reports/urls.py | 16 | path('upload/', views.VoiceUploadView.as_view(), name='voice-upload') |
| services/voice-service/voice_reports/urls.py | 17 | path('text-query/', views.TextQueryView.as_view(), name='text-query') |
| services/voice-service/voice_reports/urls.py | 20 | path('<int:report_id>/execute/', views.QueryExecuteView.as_view(), name='query-execute') |
| services/voice-service/voice_reports/urls.py | 23 | path('<int:report_id>/sql/', views.SQLEditView.as_view(), name='sql-edit') |
| services/voice-service/voice_reports/urls.py | 24 | path('<int:report_id>/ai-trace/', views.AITraceDetailView.as_view(), name='report-ai-trace') |
| services/voice-service/voice_reports/urls.py | 25 | path('<int:report_id>/chart-types/capabilities/', views.ReportChartTypeCapabilitiesView.as_view(), name='report-chart-type-capabilities') |
| services/voice-service/voice_reports/urls.py | 26 | path('<int:report_id>/chart-types/switch/', views.ReportChartTypeSwitchView.as_view(), name='report-chart-type-switch') |
| services/voice-service/voice_reports/urls.py | 29 | path('reports/', views.ReportListView.as_view(), name='report-list') |
| services/voice-service/voice_reports/urls.py | 30 | path('<int:report_id>/', views.ReportDetailView.as_view(), name='report-detail') |
| services/voice-service/voice_reports/urls.py | 33 | path('dashboard/stats/', views.DashboardStatsView.as_view(), name='dashboard-stats') |
| services/voice-service/voice_reports/urls.py | 34 | path('dashboard/', views.WorkspaceDashboardView.as_view(), name='workspace-dashboard') |
| services/voice-service/voice_reports/urls.py | 35 | path('pages/', dashboard_builder_views.DashboardPageListCreateView.as_view(), name='dashboard-page-list-create') |
| services/voice-service/voice_reports/urls.py | 36 | path('pages/reorder/', dashboard_builder_views.DashboardPageReorderView.as_view(), name='dashboard-page-reorder') |
| services/voice-service/voice_reports/urls.py | 37 | path('pages/<int:page_id>/', dashboard_builder_views.DashboardPageDetailView.as_view(), name='dashboard-page-detail') |
| services/voice-service/voice_reports/urls.py | 38 | path('pages/<int:page_id>/widgets/', dashboard_builder_views.DashboardPageWidgetListCreateView.as_view(), name='dashboard-page-widgets') |
| services/voice-service/voice_reports/urls.py | 39 | path('widgets/batch-layout/', dashboard_builder_views.DashboardWidgetBatchUpdateView.as_view(), name='dashboard-widget-batch-update') |
| services/voice-service/voice_reports/urls.py | 40 | path('widgets/<int:widget_id>/', dashboard_builder_views.DashboardWidgetDetailView.as_view(), name='dashboard-widget-detail') |
| services/workspace-service/service_config/urls.py | 9 | path('admin/workspaces/', AdminWorkspaceListView.as_view(), name='admin-workspaces') |
| services/workspace-service/service_config/urls.py | 10 | path('admin/workspaces/<int:workspace_id>/', AdminWorkspaceDetailView.as_view(), name='admin-workspace-detail') |
| services/workspace-service/service_config/urls.py | 15 | path('admin/', admin.site.urls) |
| services/workspace-service/service_config/urls.py | 16 | path('workspace/', include('workspace.urls')) |
| services/workspace-service/workspace/urls.py | 23 | path('', WorkspaceUpdateView.as_view(), name='workspace-update') |
| services/workspace-service/workspace/urls.py | 24 | path('<int:workspace_id>/', WorkspaceDetailByIdView.as_view(), name='workspace-detail') |
| services/workspace-service/workspace/urls.py | 25 | path('members/', WorkspaceMembersView.as_view(), name='workspace-members') |
| services/workspace-service/workspace/urls.py | 26 | path('invite/', InvitationView.as_view(), name='workspace-invite') |
| services/workspace-service/workspace/urls.py | 27 | path('accept-invite/', AcceptInvitationView.as_view(), name='accept-invite') |
| services/workspace-service/workspace/urls.py | 28 | path('invitation/<str:email>/', RemovePendingInvitationView.as_view(), name='remove-invitation') |
| services/workspace-service/workspace/urls.py | 29 | path('member/<int:id>/', MemberManageView.as_view(), name='member-manage') |
| services/workspace-service/workspace/urls.py | 30 | path('member/<int:id>/role/', RoleAssignmentView.as_view(), name='assign-role') |
| services/workspace-service/workspace/urls.py | 31 | path('member/<int:id>/suspend/', MemberSuspendView.as_view(), name='suspend-member') |
| services/workspace-service/workspace/urls.py | 32 | path('member/<int:id>/unsuspend/', MemberUnsuspendView.as_view(), name='unsuspend-member') |
| services/workspace-service/workspace/urls.py | 33 | path('internal/invitations/resolve/', InternalInvitationResolveView.as_view(), name='internal-invitation-resolve') |
| services/workspace-service/workspace/urls.py | 34 | path('internal/invitations/attach-user/', InternalAttachUserToInvitationView.as_view(), name='internal-invitation-attach-user') |
| services/workspace-service/workspace/urls.py | 35 | path('internal/workspaces/create-manager/', InternalCreateManagerWorkspaceView.as_view(), name='internal-create-manager-workspace') |
| services/workspace-service/workspace/urls.py | 36 | path('internal/users/<int:user_id>/workspaces/', InternalUserWorkspacesView.as_view(), name='internal-user-workspaces') |
| services/workspace-service/workspace/urls.py | 37 | path('internal/users/activate-memberships/', InternalActivateUserMembershipsView.as_view(), name='internal-activate-user-memberships') |

Target: /api/v1 for public endpoints and /internal/v1 for service APIs, one error envelope {code,message,request_id,details}, documented pagination, idempotency and timeouts. Keep old public URLs as temporary gateway aliases. Contract tests must cover success, 401, 403, 404, timeout, invalid response and unavailable dependency.

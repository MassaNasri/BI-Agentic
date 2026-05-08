# شرح مبسط لملف `views.py`

هذا الملف مسؤول عن API الخاصة بتقارير الصوت داخل `voice-service`.

## الدوال المساعدة (Functions)

- `build_report_ai_trace`
  - يجمع كل بيانات التقرير (نص، SQL، نتيجة، تشارت، أخطاء) في Payload موحّد لشرح خط سير الـ AI.

- `_build_async_accepted_response`
  - يرجّع رد `202 Accepted` بعد إنشاء Job غير متزامن مع رابط متابعة الحالة.

- `get_user_workspace`
  - يحل الـ Workspace عبر `workspace-service` (HTTP) أولاً.
  - ثم يربط النتيجة بسجل الـ Workspace المحلي (shared DB) للفلترة.
  - يوجد fallback محلي قديم فقط عند التفعيل الصريح عبر env.

- `get_report_embed_url`
  - يطلب رابط embed جديد للسؤال من `visualization-service`.

- `_service_headers_with_auth`
  - يبني headers فيها `Content-Type` و `Authorization` (إذا موجود).
  - ملاحظة: حالياً غير مستخدمة داخل الملف.

- `_resolve_dataset_binding_context`
  - يعيد سياق `workspace_id/manager_id/dataset_id/source_id/table_name` فقط من القيم الصريحة.
  - ملاحظة: حالياً غير مستخدمة داخل الملف.

- `build_default_preprocessing_low`
  - يبني شكل افتراضي لنتيجة الـ preprocessing منخفض المستوى.

- `build_default_preprocessing_high`
  - يبني شكل افتراضي لنتيجة الـ preprocessing عالي المستوى (schema-aware).

- `build_default_pipeline_trace`
  - يبني trace افتراضي لعرض حالة pipeline والسبب الجذري.

- `normalize_pipeline_trace`
  - ينظف/يوحد trace المخزن ويرجع fallback آمن إذا البيانات غير صالحة.

- `extract_pipeline_contract`
  - يستخرج Contract مبسط من trace: `status/degraded/confidence/confidence_breakdown`.

- `extract_report_contract`
  - يدمج Contract القادم من trace مع contract مخزن في `chart_config`.

- `_flatten_schema_columns`
  - يحول أعمدة schema من أشكال مختلفة إلى List موحد.

- `_dedupe_non_empty`
  - يحذف التكرار والقيم الفارغة من List نصية.

- `_extract_term_corrections_from_mappings`
  - يستخرج تصحيحات المصطلحات من `mappings`.

- `_extract_schema_adjustments_from_mappings`
  - يحول `mappings` إلى تعديلات schema بصيغة واضحة.

- `_extract_schema_usage_from_mappings`
  - يستخرج الجداول والأعمدة المستخدمة فعلياً من `mappings`.

- `normalize_preprocessing_low`
  - يوحد payload preprocessing low مهما اختلف شكله.

- `normalize_preprocessing_high`
  - يوحد payload preprocessing high ويملأ القيم الناقصة من مصادر بديلة.

- `_view_is_predictive`
  - يقرر إن الطلب تنبؤي/Forecast أم لا.

- `_view_forecast_horizon`
  - يقرأ أفق التنبؤ (horizon) من intent ويعيده كرقم صحيح.

- `_view_forecasting_config`
  - يبني Config قياسي لنتائج التنبؤ لعرضها لاحقاً.

## الكلاسات والـ Endpoints

- `VoiceUploadView.post`
  - يتحقق من ملف الصوت، يفحص الاشتراك، يخزن الصوت، ثم يطلق Job غير متزامن لمعالجة pipeline.

- `TextQueryView.post`
  - يستقبل نص، يفحص الاشتراك وصحة الـ workspace، ثم يطلق Job غير متزامن لنفس pipeline.

- `QueryExecuteView.post`
  - يعيد تنفيذ SQL (بعد تعديل أو إعادة تشغيل):
  - يتحقق من الصلاحية.
  - يحقق SQL عبر `query-service`.
  - ينفذ SQL عبر `query-service`.
  - يعالج حالة التنبؤ (forecast) إذا كانت النية تنبؤية.
  - ينشئ visualization عبر `visualization-service`.
  - يحدث التقرير النهائي وحالته.

- `SQLEditView.put`
  - يسمح للمحلل بتعديل SQL بعد التحقق منه، ويضع التقرير بحالة pending لإعادة التنفيذ.

- `ReportListView.get`
  - يرجع قائمة التقارير ضمن workspace مع بعض حقول التلخيص.

- `ReportDetailView.get`
  - يرجع تفاصيل تقرير كامل: SQL، trace، preprocessing، contract، embed URL...

- `ReportDetailView.delete`
  - حذف تقرير (Manager فقط، ومنشئ التقرير نفسه).

- `AITraceDetailView.get`
  - يرجع `ai_trace` مفصل للمحللين.

- `WorkspaceDashboardView.get`
  - يرجع رابط embed للداشبورد الخاص بالـ workspace.

- `DashboardStatsView.get`
  - يرجع إحصائيات Dashboard (عدد التقارير، الفاشلة، المكتملة، قيد المعالجة، مجموع الصفوف).

- `JobStatusView.get`
  - endpoint قياسي لمتابعة Job غير المتزامن (`status/stage/progress/error`).

- `HealthCheckView.get`
  - يفحص صحة الاتصال مع `ai-service` و`query-service` و`visualization-service`.

---

## مشاكل الملف حالياً

- الملف كبير جداً (أكثر من 1500 سطر) وفيه مسؤوليات كثيرة (Validation + Orchestration + Persistence + Response shaping).
- تكرار كبير لمنطق `workspace` والتحقق من المستخدم في أغلب الـ views.
- وجود دوال غير مستخدمة حالياً: `_service_headers_with_auth` و `_resolve_dataset_binding_context`.
- منطق أعمال ثقيل داخل `QueryExecuteView.post` (تنفيذ SQL + Forecast + Visualization + تحديثات متعددة للحالة).
- ما زال هناك اقتران جزئي بسبب shared DB وعلاقات FK، لكن لم يعد هناك تنفيذ مباشر لمنطق workspace داخل `views.py`.

## هل الملف يعمل أكثر من وظيفته؟

نعم. بدل أن يكون فقط طبقة API خفيفة، هو أيضاً:
- ينفذ قواعد عمل معقدة.
- يقرر fallback وسيناريوهات degraded.
- ينسق بين عدة خدمات.
- يعيد تشكيل traces/contracts.

هذا يعني "Controller + Service + جزء من Domain" في ملف واحد.

## هل يحقق مبادئ Microservices؟

- يحققها جزئياً:
  - ممتاز أنه يتواصل HTTP مع خدمات خارجية (`query-service`, `visualization-service`, `subscription-service`, `workspace-service`).
- لا يحققها بالكامل:
  - ما زال فيه اقتران بيانات (data coupling) بسبب shared DB.
  - `voice_reports.models` ما زال مرتبطاً جدوليًا بـ Workspace (لكن بدون import مباشر للكود).

## كيف نخليه أقرب لـ Microservices بدون كسر النظام؟

- المرحلة 1 (آمنة وسريعة):
  - إبقاء المجلدات الحالية مؤقتاً.
  - إيقاف أي fallback محلي (`VOICE_SERVICE_ALLOW_LOCAL_WORKSPACE_FALLBACK=false`).
  - جعل الاعتماد الأساسي على claims من التوكن + `workspace-service` HTTP فقط.

- المرحلة 2 (فصل المنطق):
  - نقل منطق `get_user_workspace` إلى `workspace_client` فقط.
  - استخراج منطق `QueryExecuteView` إلى service/use-case classes منفصلة.

- المرحلة 3 (فك اقتران قاعدة البيانات):
  - استبدال `ForeignKey(Workspace)` بـ `workspace_id` (UUID/Char) داخل `voice_reports`.
  - استبدال الاعتماد المباشر على user object في الداتا الحساسة بـ `created_by_id` + بيانات هوية من التوكن.
  - إضافة migration انتقالية متدرجة مع backfill.

- المرحلة 4 (تنظيف نهائي):
  - بعد نجاح المراحل السابقة واختبارات التكامل، إزالة الاعتماد المحلي على apps `users/workspace`.

## هل أحذف مجلد `users` و `workspaces` الآن؟

لا، ليس الآن.

الحذف المباشر سيكسر النظام بسبب:
- علاقات ORM/جداول مشتركة لازالت مستخدمة.
- بقاء أجزاء legacy fallback المحلي إذا تم تفعيلها.

الحل الصحيح: نفك الارتباط تدريجياً أولاً، ثم نحذف بعد التأكد من اكتمال الترحيل والاختبارات.

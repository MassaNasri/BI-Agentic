# تقرير كشف الواجهات: Home / Signup / Login

## 1) نطاق التحليل

تم تحليل الصفحات التالية في الواجهة الأمامية:
- `Home` (`src/pages/Home.jsx`)
- `Signup` (اعتبارًا أن كلمة `sin an` المقصودة هي `Sign up`) (`src/pages/auth/Signup.jsx`)
- `Login` (`src/pages/auth/Login.jsx`)

وشمل التحليل أيضًا الملفات المرتبطة مباشرة بهذه الصفحات:
- الراوتينغ: `src/App.jsx`, `src/main.jsx`, `src/layouts/AuthLayout.jsx`
- الأنيميشن: `src/animations/homeVariants.js`, `src/animations/formVariants.js`, `src/animations/variants.js`
- الـAPI والمصادقة: `src/api/axios.js`, `src/api/endpoints.js`, `src/store/auth.js`
- المكونات المشتركة: `src/components/Button.jsx`, `src/components/Input.jsx`, `src/components/Select.jsx`, `src/components/ErrorAlert.jsx`
- الستايل العام: `src/styles/index.css`, `tailwind.config.js`

---

## 2) طريقة تصميم الواجهات المستخدمة

### المعمارية الأمامية
- **Framework**: React (Vite)
- **Routing**: `react-router-dom` مع `Routes/Route`, `Navigate`, و`Layout-based routing`
- **State Management**: `zustand` + `persist` لتخزين حالة المستخدم
- **UI Styling**: Tailwind CSS (أسلوب Utility-first) + Classes مخصصة مثل `btn`, `card`, `input`
- **Icons**: `lucide-react`

### أسلوب بناء الواجهة
- **Component-based UI**: حقول الإدخال، الأزرار، التنبيهات مفصولة كمكوّنات قابلة لإعادة الاستخدام.
- **Design System خفيف**:
  - ألوان رئيسية موسعة في Tailwind تحت `primary` (من 50 إلى 900).
  - أشكال موحدة: `rounded-lg/rounded-xl`, `shadow`, `focus:ring`.
- **Visual Language**:
  - خلفيات متدرجة (`bg-gradient-to-br`) مع دوائر ضبابية عائمة.
  - بطاقات شبه شفافة مع `backdrop-blur-sm` في صفحات التسجيل/الدخول.

---

## 3) الأنيميشن المطبق على الصفحات

## 3.1 أنيميشن الصفحة Home
- مكتبة الأنيميشن الأساسية: **Framer Motion**.
- دخول الصفحة: `pageVariants` (Fade-in + stagger children).
- Navbar: هبوط خفيف للأعلى/الأسفل (`y: -20 -> 0`).
- Badge/Title/Subtitle: مزيج fade + scale + slide.
- الأزرار: `hover` تكبير بسيط و`tap` تصغير خفيف.
- بطاقات الميزات:
  - دخول متدرج Stagger.
  - Hover: رفع البطاقة للأعلى + ظل أكبر.
- عناصر الخلفية العائمة:
  - حركات لانهائية (`repeat: Infinity`) بمحاور `x/y/scale`.
  - مدد مختلفة (8s/10s/12s) لإحساس حي.
- CTA:
  - تكبير خفيف عند hover.
  - أيقونة الدرع بنبض مستمر `scale: [1, 1.1, 1]`.
- **CSS Animation إضافية**:
  - `animate-gradient` لتحريك تدرج النص الكبير (مدة 6s وتكرار لا نهائي).

## 3.2 أنيميشن صفحات Signup/Login
- `pageWrapperVariants`: Fade-in للصفحة بالكامل.
- `formContainerVariants`: دخول نموذج بصيغة slide-up + scale.
- `iconContainerVariants`: ظهور الأيقونة بأسلوب spring.
- `formFieldsContainerVariants` + `formFieldVariants`: ظهور متدرج لحقول النموذج.
- `submitButtonVariants`: تأثير hover/tap للزر.
- `alertVariants`: دخول/خروج رسائل النجاح/الخطأ بـ AnimatePresence.
- `errorShakeVariants`: هزة أفقية للنموذج عند فشل API.
- خلفية متحركة بعناصر blob عائمة (متوافقة مع ستايل Home).

## 3.3 أنيميشن داخل المكوّنات المشتركة
- `Button`: hover/tap + دوران spinner عند التحميل.
- `Input`: تكبير خفيف أثناء التركيز + ظهور رسالة الخطأ بشكل animate.
- `ErrorAlert`: Enter/Exit animations مع إغلاق تلقائي (`autoDismiss` افتراضيًا).

---

## 4) أنواع الـAPI المستخدمة في هذه الصفحات

## 4.1 النمط العام
- **REST API عبر HTTP** باستخدام `axios`.
- **JSON payloads** للطلبات/الردود.
- **JWT Authentication** (Bearer Token) عبر `Authorization` header.

## 4.2 API المستخدمة فعليًا من صفحات Signup/Login
- `POST /auth/signup/` عبر `authAPI.signup(data)` (صفحة Signup).
- `POST /auth/login/` عبر `authAPI.login({ email, password })` (صفحة Login).

## 4.3 إدارة التوكن
- بعد نجاح Login:
  - يتم حفظ `access_token` و`refresh_token` في `localStorage`.
  - يتم تحديث Zustand store (`user`, `workspace`, `isAuthenticated`).
- عند أي 401 (غير public endpoints):
  - Interceptor ينفذ `POST /auth/token/refresh/`.
  - يعيد محاولة الطلب الأصلي تلقائيًا.
- عند فشل التحديث:
  - حذف التوكنات وإعادة توجيه مباشرة إلى `/login`.

## 4.4 أنواع أخرى للـAPI في نفس طبقة الواجهة (ضمن المشروع)
- `GET`, `POST`, `PUT`, `PATCH`, `DELETE`.
- `multipart/form-data` (موجودة في طبقات أخرى مثل رفع ملفات/صوت، ليست مستخدمة مباشرة في Home/Login/Signup).

---

## 5) الانتقالات (Navigation Flow)

## 5.1 من Home
- زر **Create Free Account** -> `/signup`
- زر **Sign In** -> `/login`
- زر CTA **Start Free Today** -> `/signup`

## 5.2 من Signup
- نجاح التسجيل:
  - عادي -> `/verify-email?sent=true`
  - عبر دعوة Workspace -> `/verify-email?sent=true&invited=true`
- روابط يدوية:
  - إلى Login: `/login`
  - إلى Home: `/`

## 5.3 من Login
- نجاح تسجيل الدخول:
  - إذا `role=admin` -> `/admin-dashboard`
  - غير ذلك -> `/dashboard`
- روابط يدوية:
  - Forgot Password -> `/forgot-password`
  - Create Account -> `/signup`
  - Back to Home -> `/`

## 5.4 حماية المسارات
- `PrivateRoute` في `App.jsx`:
  - يمنع الوصول دون مصادقة.
  - يطبق صلاحيات حسب الدور (`admin`, `manager`, `analyst`, `executive`).
- `AuthLayout`:
  - إذا المستخدم مسجل بالفعل -> إعادة توجيه تلقائية إلى `/dashboard`.

---

## 6) تفاصيل UX المرتبطة بالواجهات

- Loading states واضحة في الأزرار (`Signing in...`, `Creating account...`).
- Validation محلي في Signup:
  - التحقق من الاسم، الإيميل، وطول كلمة المرور (8+).
- رسائل خطأ وسيناريوهات دعوة Workspace:
  - رسائل متحركة مع خيار إغلاق.
- `react-hot-toast` مستخدم كتنبيهات عامة لنجاح/فشل العمليات.

---

## 7) ملاحظات تقنية مهمة

- هناك مشاكل ترميز نصي ظاهرة داخل بعض النصوص في `Login.jsx` و`Signup.jsx` مثل:
  - `ðŸŽ‰` بدل emoji
  - `â€¢â€¢â€¢...` بدل placeholder نقطي واضح
  - `â†` بدل سهم الرجوع
- هذا لا يوقف التنفيذ، لكنه يؤثر على جودة العرض النصي في الواجهة.

---

## 8) خلاصة سريعة

- الواجهات مبنية بأسلوب حديث: React + Tailwind + Framer Motion + Zustand.
- الأنيميشن غني وموزع بين:
  - دخول/خروج الصفحات
  - تفاعلات hover/tap
  - خلفيات ديناميكية مستمرة
  - رسائل تنبيه متحركة
- المصادقة تعتمد REST + JWT مع refresh تلقائي عند انتهاء صلاحية التوكن.
- التنقلات واضحة ومبنية على حالات المستخدم والدور (Role-based routing).

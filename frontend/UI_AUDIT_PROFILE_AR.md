# تقرير كشف واجهة Profile

## 1) نطاق الكشف

تم تنفيذ كشف كامل لواجهة `Profile` وكل الطبقات المرتبطة بها في الواجهة الأمامية، بما يشمل:
- تصميم الصفحة وبنية الـ Layout
- الأنيميشن (على مستوى الصفحة، العناصر، والأزرار)
- أنواع واستعمالات الـ API
- الانتقالات (Routing + Navigation)
- إدارة الحالة (State) والتحقق من الإدخال (Validation)

## 2) الملفات التي تم تحليلها

### ملفات الصفحة نفسها
- `frontend/src/pages/profile/Profile.jsx`

### ملفات التخطيط والتنقل
- `frontend/src/App.jsx`
- `frontend/src/layouts/DashboardLayout.jsx`
- `frontend/src/components/AnimatedPage.jsx`
- `frontend/src/main.jsx`

### ملفات الـ API والحالة
- `frontend/src/api/endpoints.js`
- `frontend/src/api/axios.js`
- `frontend/src/store/auth.js`

### ملفات المكونات المشتركة المستخدمة في Profile
- `frontend/src/components/Card.jsx`
- `frontend/src/components/Input.jsx`
- `frontend/src/components/Button.jsx`
- `frontend/src/components/Badge.jsx`
- `frontend/src/components/Modal.jsx`
- `frontend/src/components/index.js`

### ملفات التصميم والأنيميشن
- `frontend/src/animations/uiVariants.js`
- `frontend/src/animations/variants.js`
- `frontend/src/styles/index.css`
- `frontend/tailwind.config.js`
- `frontend/package.json`

---

## 3) طريقة تصميم الواجهات المستخدمة (Design Approach)

### المعمارية الأمامية
- **Framework**: React 18 (Vite)
- **Styling**: Tailwind CSS + Utility classes + Component classes (`.btn`, `.card`, `.input`, `.badge`)
- **UI Composition**: Component-based architecture
- **State Management**: Zustand (مع `persist`)
- **Icons**: Lucide React

### منهج تصميم صفحة Profile
- الصفحة مبنية على `AnimatedPage` كـ wrapper للانتقال البصري.
- المحتوى موزع على **بطاقات مستقلة** (Cards) تمثل أقسامًا واضحة:
  - Profile Information
  - Security
  - Account Information
  - Danger Zone
- نمط الصفحة يعتمد على:
  - `max-w-4xl mx-auto` لتوسيط المحتوى ضمن مساحة قراءة مناسبة.
  - فصل وظيفي بصري لكل قسم داخل Card.
  - نموذج إدخال حقول مع تحقق (Validation) ورسائل خطأ مباشرة.

### نظام الألوان والطباعة
- الألوان معرفة جزئيًا عبر:
  - Tailwind extended palette (`brand`, `primary`, `fire`, `amber`) في `tailwind.config.js`
  - CSS variables في `index.css` مثل `--c-card-bg`, `--c-border`
- الطباعة:
  - `DM Sans` للنصوص
  - `Syne` للعناوين الأساسية

### المكونات المستخدمة في الواجهة
- **Card**: حاوية موحدة للأقسام.
- **Input**: حقول مع أيقونات ودعم error animation.
- **Button**: حالات `primary/secondary/danger` + loading.
- **Badge**: عرض حالة الدور، التفعيل، والتحقق.
- **Modal**: نافذتان للحالات الحساسة:
  - تغيير كلمة المرور
  - تعطيل الحساب

---

## 4) الأنيميشن المطبق على واجهة Profile

## 4.1 على مستوى الصفحة (Page-Level)
- `AnimatedPage`:
  - دخول: `opacity 0 -> 1`, `y 20 -> 0`
  - خروج: `opacity 1 -> 0`, `y 0 -> -20`

## 4.2 على مستوى أقسام Profile
- مستخدم من `uiVariants.js`:
  - `headerTitle`: حركة دخول للعنوان من أعلى.
  - `scaleFade`: ظهور البطاقات بتأثير scale + fade.
  - `staggerFast` و`staggerContainer`: إظهار متدرج للعناصر.
  - `listItem`: دخول عناصر النماذج والقوائم بحركة `y`.
  - `badgeScale`: ظهور الشارات بتكبير خفيف.
  - `glowHover`: تأثير توهج وتكبير بسيط حول زر الحفظ.

## 4.3 تفاعلات مباشرة
- أزرار الحفظ/الخطر:
  - `whileHover` و`whileTap` عبر Framer Motion.
- `Input`:
  - تكبير طفيف على التركيز.
  - رسائل الخطأ تدخل/تخرج عبر `AnimatePresence`.
- `Button`:
  - hover scale + tap scale.
  - spinner متحرك لحالات التحميل.

## 4.4 أنيميشن الانتقال بين الصفحات
- في `App.jsx`: `AnimatePresence mode="wait"` يضيف transition عند تبديل route.
- في `DashboardLayout.jsx`: 
  - الـ sidebar overlay mobile فيه fade in/out.
  - عناصر القائمة الجانبية تدخل تدريجيًا (`slideInLeft`) مع hover motion.

---

## 5) أنواع الـ API المستخدمة في صفحة Profile

الواجهة تستخدم **REST APIs** عبر Axios مع JWT.

## 5.1 الـ Endpoints المباشرة لصفحة Profile

1. `GET /user/profile/`
- الاستخدام: جلب بيانات المستخدم عند فتح الصفحة (`loadProfile`).
- النوع: قراءة بيانات.

2. `PUT /user/profile/`
- الاستخدام: تحديث البيانات الشخصية.
- الملاحظة: يتم إرسال الحقول المتغيرة فقط (diff payload).

3. `POST /user/change-password/`
- الاستخدام: تغيير كلمة المرور من Modal الأمان.

4. `DELETE /user/deactivate/`
- الاستخدام: تعطيل الحساب من Danger Zone.
- payload يحتوي `refresh` token داخل `data`.

## 5.2 أنواع HTTP المستخدمة (ضمن Profile)
- `GET`
- `PUT`
- `POST`
- `DELETE`

## 5.3 طبقة المصادقة وحقن التوكن
- `apiClient` يضيف `Authorization: Bearer <access_token>` تلقائيًا.
- عند `401`:
  - محاولة `POST /auth/token/refresh/`
  - إعادة تنفيذ الطلب الأصلي عند نجاح refresh.
  - تسجيل خروج وإعادة توجيه `/login` عند فشل refresh.

---

## 6) الانتقالات (Navigation Flow) الخاصة بواجهة Profile

1. الوصول إلى الصفحة:
- المسار: `/dashboard/profile`
- مسموح للأدوار: `manager`, `analyst`, `executive` (محمي عبر `PrivateRoute`).

2. انتقالات داخل الصفحة:
- زر `Reset Changes`: يعيد تحميل البيانات من API (`loadProfile`) دون تغيير route.
- زر `Change Password`: يفتح Modal محلي.
- زر `Deactivate Account`: يفتح Modal تأكيد.
- بعد نجاح التعطيل:
  - تنفيذ logout
  - `navigate('/login')`

3. انتقالات غير مباشرة مرتبطة بالـ layout:
- فتح/إغلاق sidebar في DashboardLayout.
- تنقل القائمة الجانبية إلى الصفحات الأخرى حسب الدور.

---

## 7) إدارة الحالة (State) والتحقق (Validation)

### الحالة المحلية داخل Profile
- `profile`, `originalProfile`
- `errors`, `passwordErrors`
- حالات التحميل:
  - `isLoading`
  - `isChangingPassword`
  - `isDeactivating`
- حالات الـ modals:
  - `showChangePasswordModal`
  - `showDeactivateModal`

### التحقق
- Profile form:
  - `first_name` إجباري
  - `last_name` إجباري
- Password form:
  - `current_password` إجباري
  - `new_password` إجباري
  - مطابقة `new_password` مع `confirm_new_password`

### التكامل مع Zustand
- بعد جلب/تحديث الـ profile يتم `updateUser()` لتحديث بيانات المستخدم المخزنة عالميًا.
- logout ينظف localStorage + store ويحدث إعادة توجيه.

---

## 8) ملاحظات UX/UI وسلوك المستخدم

1. الصفحة تقدم تقسيمًا واضحًا جدًا بين:
- تعديل البيانات الشخصية
- إجراءات الأمان
- معلومات الحساب
- الإجراءات الخطرة

2. الإجراءات الحساسة محمية بصريًا وسلوكيًا:
- `Danger Zone` بلون أحمر + تحذير واضح.
- تأكيد إضافي داخل Modal قبل التعطيل.

3. تجربة التفاعل جيدة بسبب:
- Loading feedback داخل الأزرار
- Toast notifications للنجاح/الفشل
- Error mapping من backend إلى حقول محددة في تغيير كلمة المرور

4. البريد الإلكتروني معروض كـ read-only (غير قابل للتعديل مباشرة).

---

## 9) الخلاصة

واجهة `Profile` مبنية بأسلوب حديث ومتماسك:
- **تصميم**: Component-based + Tailwind + Design tokens
- **أنيميشن**: Framer Motion على مستويات متعددة (صفحة/أقسام/عناصر)
- **API**: REST + JWT + Auto refresh token
- **تنقل**: Role-based routing + transitions محسّنة
- **UX**: تغذية راجعة ممتازة مع حماية واضحة للإجراءات الحساسة

النتيجة: صفحة ملف شخصي قوية وظيفيًا، واضحة بصريًا، وتغطي حالات الاستخدام الأساسية والمتقدمة (تعديل بيانات، تغيير كلمة مرور، تعطيل حساب) ضمن تجربة استخدام احترافية.

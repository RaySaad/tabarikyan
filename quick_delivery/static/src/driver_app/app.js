/* تطبيق المندوب - جافاسكربت خام، بلا إطار ولا مكتبة خارجية.
 *
 * بديل تطبيق Flutter/APK: نفس الوظائف، بلا توزيع ملف ولا تحديث يدوي
 * على كل جهاز - المندوب يفتح الرابط، يُثبّته على الشاشة الرئيسية، ثم
 * يدخل بجواله ورمزه السري.
 */
(function () {
    'use strict';

    var API_LOGIN = '/api/v1/driver/login';
    var API_LOGOUT = '/api/v1/driver/logout';
    var API_STATE = '/api/v1/driver/state';
    var SESSION_KEY = 'qd_driver_session';
    var POLL_MS = 8000;
    var LATE_SECONDS = 600;

    var session = null;        // {token, name}
    var isOnline = false;      // حالة الوردية، لا حالة الشبكة
    var order = null;
    var remaining = 0;
    var position = { lat: null, lng: null };
    var photoPayload = null;
    var pollTimer = null;
    var tickTimer = null;
    var geoWatch = null;
    var wakeLock = null;
    var busy = false;
    var audioCtx = null;
    var installEvent = null;
    var toastTimer = null;

    function $(id) { return document.getElementById(id); }

    // ==================================================================
    // التخزين المحلي - قد يكون محجوباً في نافذة خاصة فلا نسقط لذلك
    // ==================================================================
    function loadSession() {
        try {
            var raw = window.localStorage.getItem(SESSION_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch (err) { return null; }
    }

    function saveSession(value) {
        try {
            if (value) {
                window.localStorage.setItem(SESSION_KEY, JSON.stringify(value));
            } else {
                window.localStorage.removeItem(SESSION_KEY);
            }
        } catch (err) { /* الجلسة تبقى في الذاكرة لهذه الصفحة */ }
    }

    // ==================================================================
    // التنبيهات
    // ==================================================================
    function toast(message, kind) {
        var box = $('toast');
        box.textContent = message;
        box.className = 'qd-toast' + (kind ? ' qd-toast--' + kind : '');
        box.classList.remove('hidden');
        if (toastTimer) { window.clearTimeout(toastTimer); }
        toastTimer = window.setTimeout(function () {
            box.classList.add('hidden');
        }, kind === 'error' ? 6000 : 3200);
    }

    function beep() {
        // صوت مُولَّد محلياً: النسخة السابقة كانت تجلبه من
        // actions.google.com - فلا صوت بلا إنترنت ولا على شبكة محجوبة.
        try {
            if (!audioCtx) {
                var Ctor = window.AudioContext || window.webkitAudioContext;
                if (!Ctor) { return; }
                audioCtx = new Ctor();
            }
            if (audioCtx.state === 'suspended') { audioCtx.resume(); }
            [0, 0.18].forEach(function (offset) {
                var osc = audioCtx.createOscillator();
                var gain = audioCtx.createGain();
                osc.type = 'sine';
                osc.frequency.value = 880;
                gain.gain.setValueAtTime(0.0001, audioCtx.currentTime + offset);
                gain.gain.exponentialRampToValueAtTime(
                    0.3, audioCtx.currentTime + offset + 0.02);
                gain.gain.exponentialRampToValueAtTime(
                    0.0001, audioCtx.currentTime + offset + 0.15);
                osc.connect(gain);
                gain.connect(audioCtx.destination);
                osc.start(audioCtx.currentTime + offset);
                osc.stop(audioCtx.currentTime + offset + 0.16);
            });
        } catch (err) { /* الصوت ترف، لا نُسقط التطبيق لأجله */ }
        try {
            if (navigator.vibrate) { navigator.vibrate([200, 90, 200]); }
        } catch (err) { /* ignore */ }
    }

    // ==================================================================
    // نداءات الخادم
    // ==================================================================
    function callApi(url, body, withAuth) {
        var headers = { 'Content-Type': 'application/json' };
        if (withAuth !== false && session) {
            headers.Authorization = 'Bearer ' + session.token;
        }
        return window.fetch(url, {
            method: 'POST',
            headers: headers,
            body: JSON.stringify(body || {})
        }).then(function (response) {
            setNetworkBar(false);
            return response.json().catch(function () {
                return { status: 'error', error: 'رد غير مفهوم من الخادم' };
            }).then(function (data) {
                if (!response.ok) {
                    var error = new Error(data.error || 'تعذّر تنفيذ الطلب');
                    error.code = data.code;
                    error.status = response.status;
                    throw error;
                }
                return data;
            });
        }, function () {
            setNetworkBar(true);
            var error = new Error('لا يوجد اتصال بالخادم - سنعيد المحاولة');
            error.offline = true;
            throw error;
        });
    }

    function handleApiError(error) {
        if (error && error.code === 'session_expired') {
            endSession(false);
            toast('انتهت الجلسة - يُرجى الدخول من جديد', 'error');
            return;
        }
        if (error && error.offline) { return; }   // شريط الشبكة يكفي
        toast((error && error.message) || 'حدث خطأ', 'error');
    }

    // ==================================================================
    // الشبكة والموقع والشاشة
    // ==================================================================
    function setNetworkBar(down) {
        $('networkBar').classList.toggle('hidden', !down);
    }

    function startGeo() {
        if (geoWatch !== null || !navigator.geolocation) { return; }
        geoWatch = navigator.geolocation.watchPosition(function (pos) {
            position.lat = pos.coords.latitude;
            position.lng = pos.coords.longitude;
        }, function (err) {
            if (err && err.code === 1) {
                toast('صلاحية الموقع مرفوضة - لن تصلك طلبات قريبة حتى '
                      + 'تسمح بالموقع من إعدادات المتصفح', 'error');
            }
        }, { enableHighAccuracy: true, maximumAge: 15000, timeout: 20000 });
    }

    function stopGeo() {
        if (geoWatch !== null && navigator.geolocation) {
            navigator.geolocation.clearWatch(geoWatch);
        }
        geoWatch = null;
    }

    function requestWakeLock() {
        if (!navigator.wakeLock || wakeLock) { return; }
        navigator.wakeLock.request('screen').then(function (lock) {
            wakeLock = lock;
            lock.addEventListener('release', function () { wakeLock = null; });
        }).catch(function () { /* غير مدعوم أو مرفوض */ });
    }

    function releaseWakeLock() {
        if (wakeLock) {
            try { wakeLock.release(); } catch (err) { /* ignore */ }
            wakeLock = null;
        }
    }

    // ==================================================================
    // الدخول والخروج
    // ==================================================================
    function showLogin() {
        $('screen-login').classList.remove('hidden');
        $('screen-app').classList.add('hidden');
    }

    function showApp() {
        $('screen-login').classList.add('hidden');
        $('screen-app').classList.remove('hidden');
    }

    function doLogin() {
        var phone = $('loginPhone').value.trim();
        var pin = $('loginPin').value.trim();
        if (!phone || !pin) {
            $('loginError').textContent = 'أدخل رقم الجوال ورمز الدخول';
            $('loginError').classList.remove('hidden');
            return;
        }
        var button = $('loginBtn');
        button.disabled = true;
        button.textContent = 'جاري الدخول...';
        $('loginError').classList.add('hidden');

        callApi(API_LOGIN, { phone: phone, pin: pin }, false).then(function (data) {
            session = { token: data.token, name: data.driver.name };
            saveSession(session);
            $('loginPin').value = '';
            startApp();
        }).catch(function (error) {
            $('loginError').textContent = error.message || 'تعذّر الدخول';
            $('loginError').classList.remove('hidden');
        }).then(function () {
            button.disabled = false;
            button.textContent = 'دخول';
        });
    }

    function endSession(callServer) {
        stopPolling();
        stopGeo();
        releaseWakeLock();
        isOnline = false;
        order = null;
        var token = session && session.token;
        session = null;
        saveSession(null);
        $('onlineSwitch').checked = false;
        showLogin();
        if (callServer && token) {
            window.fetch(API_LOGOUT, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json',
                           'Authorization': 'Bearer ' + token },
                body: '{}'
            }).catch(function () { /* الجلسة تنتهي بنفسها على الخادم */ });
        }
    }

    function startApp() {
        showApp();
        $('driverName').textContent = session.name || 'مندوب التوصيل';
        renderTopBar();
        startPolling();
        // نداء أول فوراً: المندوب قد يكون "متاح" على الخادم من جهاز آخر
        // أو من جلسة سابقة، وعليه طلب حيّ يجب أن يراه قبل ثماني ثوان.
        sync(null);
    }

    // ==================================================================
    // الوردية
    // ==================================================================
    function toggleOnline(checked) {
        isOnline = checked;
        renderTopBar();
        if (checked) {
            startGeo();
            requestWakeLock();
            beep();            // يفتح قناة الصوت بإيماءة المستخدم
        } else {
            releaseWakeLock();
        }
        sync(checked ? 'online' : 'offline');
    }

    function renderTopBar() {
        $('topBar').classList.toggle('is-online', isOnline);
        $('statusLabel').textContent = isOnline
            ? (order ? 'في مهمة توصيل' : 'متاح لاستقبال الطلبات')
            : 'غير متصل - لا تصلك طلبات';
    }

    function startPolling() {
        stopPolling();
        pollTimer = window.setInterval(function () { sync(null); }, POLL_MS);
        tickTimer = window.setInterval(tickCountdown, 1000);
    }

    function stopPolling() {
        if (pollTimer) { window.clearInterval(pollTimer); pollTimer = null; }
        if (tickTimer) { window.clearInterval(tickTimer); tickTimer = null; }
    }

    function sync(setStatus) {
        if (!session) { return; }
        var body = { lat: position.lat, lng: position.lng };
        if (setStatus) { body.set_status = setStatus; }
        callApi(API_STATE, body).then(function (data) {
            applyState(data);
        }).catch(function (error) {
            if (error && !error.offline && setStatus === 'offline') {
                // "لا يمكن الانصراف وعليك طلب حيّ": نُعيد المفتاح لحاله
                // بدل إظهار مندوب منصرف وهو في مهمة.
                isOnline = true;
                $('onlineSwitch').checked = true;
                renderTopBar();
            }
            handleApiError(error);
        });
    }

    function applyState(data) {
        if (data.driver_name) { $('driverName').textContent = data.driver_name; }
        // الخادم هو المرجع في الحالة: جهاز آخر أو غرفة العمليات قد
        // تُغيّرها.
        isOnline = data.driver_status !== 'offline';
        $('onlineSwitch').checked = isOnline;

        var wallet = data.wallet || {};
        $('walletCod').textContent = formatMoney(wallet.cod_custody);
        $('walletOrders').textContent = wallet.today_orders || 0;
        $('walletEarnings').textContent = formatMoney(wallet.today_earnings);

        var hadOrder = !!order;
        if (data.has_order) {
            order = data.order;
            remaining = order.remaining_seconds;
            if (!hadOrder) { beep(); }
            renderOrder();
        } else {
            order = null;
            renderEmpty();
        }
        renderTopBar();
    }

    function formatMoney(value) {
        var number = Number(value || 0);
        return number.toFixed(2) + ' ر.س';
    }

    // ==================================================================
    // العرض
    // ==================================================================
    function renderEmpty() {
        $('orderBox').classList.add('hidden');
        $('failBox').classList.add('hidden');
        $('stateOffline').classList.toggle('hidden', isOnline);
        $('stateWaiting').classList.toggle('hidden', !isOnline);
    }

    function renderOrder() {
        $('stateOffline').classList.add('hidden');
        $('stateWaiting').classList.add('hidden');
        $('orderBox').classList.remove('hidden');

        $('orderRef').textContent = order.merchant_order_id;
        $('clientChip').textContent = order.client_name || '';
        $('storeName').textContent = order.store_name || '-';
        $('storeMeta').textContent = 'عدد الأكياس: ' + (order.bags_count || 1);
        $('customerName').textContent = order.customer_name || '-';
        $('customerMeta').textContent = (order.address_notes || 'بلا وصف عنوان');
        $('callBtn').href = 'tel:' + (order.customer_phone || '');

        var codBox = $('codBox');
        if (order.cod_amount > 0) {
            codBox.textContent = 'مطلوب تحصيل: ' + formatMoney(order.cod_amount);
            codBox.classList.remove('hidden');
        } else {
            codBox.classList.add('hidden');
        }

        var toStore = (order.state === 'driver_assigned'
                       || order.state === 'arrived_at_store');
        var lat = toStore ? order.store_lat : order.customer_lat;
        var lng = toStore ? order.store_lng : order.customer_lng;
        $('navBtn').href = 'https://www.google.com/maps/dir/?api=1'
            + '&destination=' + lat + ',' + lng + '&travelmode=driving';
        $('navBtn').textContent = toStore
            ? 'التوجّه إلى فرع ' + (order.store_name || 'السوبرماركت')
            : 'التوجّه إلى موقع العميل';

        var step = $('stepBtn');
        var pod = $('podBox');
        if (order.state === 'driver_assigned') {
            pod.classList.add('hidden');
            step.textContent = 'وصلت إلى الفرع';
            step.className = 'qd-btn qd-btn--step';
        } else if (order.state === 'arrived_at_store') {
            pod.classList.add('hidden');
            step.textContent = 'استلمت الأكياس - بدء التوصيل';
            step.className = 'qd-btn qd-btn--nav';
        } else {
            pod.classList.remove('hidden');
            step.textContent = 'تأكيد التسليم للعميل';
            step.className = 'qd-btn qd-btn--primary';
        }
        tickCountdown(true);
    }

    function tickCountdown(force) {
        if (!order) { return; }
        if (!force && remaining > 0) { remaining -= 1; }
        var minutes = Math.floor(Math.abs(remaining) / 60);
        var seconds = Math.abs(remaining) % 60;
        var text = (remaining < 0 ? '-' : '')
            + String(minutes).padStart(2, '0') + ':'
            + String(seconds).padStart(2, '0');
        $('slaValue').textContent = text;
        $('slaBox').classList.toggle('is-late', remaining < LATE_SECONDS);
        $('slaLabel').textContent = remaining <= 0
            ? 'تجاوز الوقت المستهدف'
            : 'الوقت المتبقي للتسليم';
    }

    // ==================================================================
    // الصورة: تصغير قبل الإرسال
    // ==================================================================
    function preparePhoto(file) {
        // صورة جوال خام = أربعة ميجابايت، أي خمسة ونصف بعد base64 على
        // شبكة جوال. نُصغّرها في الجهاز: الإثبات لا يحتاج دقة كاملة.
        return new Promise(function (resolve, reject) {
            var reader = new FileReader();
            reader.onerror = function () { reject(new Error('تعذّر قراءة الصورة')); };
            reader.onload = function () {
                var image = new Image();
                image.onerror = function () { reject(new Error('الملف ليس صورة')); };
                image.onload = function () {
                    var max = 1280;
                    var scale = Math.min(1, max / Math.max(image.width, image.height));
                    var canvas = document.createElement('canvas');
                    canvas.width = Math.round(image.width * scale);
                    canvas.height = Math.round(image.height * scale);
                    canvas.getContext('2d').drawImage(
                        image, 0, 0, canvas.width, canvas.height);
                    resolve(canvas.toDataURL('image/jpeg', 0.72));
                };
                image.src = reader.result;
            };
            reader.readAsDataURL(file);
        });
    }

    function onPhotoChosen(event) {
        var file = event.target.files && event.target.files[0];
        if (!file) { return; }
        preparePhoto(file).then(function (dataUrl) {
            photoPayload = dataUrl;
            $('photoLabel').classList.add('is-set');
            $('photoLabelText').textContent = 'تم التقاط صورة الإثبات ✓';
        }).catch(function (error) {
            photoPayload = null;
            toast(error.message, 'error');
        });
    }

    // ==================================================================
    // الانتقالات
    // ==================================================================
    function nextState() {
        if (!order) { return null; }
        if (order.state === 'driver_assigned') { return 'arrived_at_store'; }
        if (order.state === 'arrived_at_store') { return 'picked_up'; }
        if (order.state === 'picked_up') { return 'delivered'; }
        return null;
    }

    function advance() {
        if (busy || !order) { return; }
        var target = nextState();
        if (!target) { return; }
        var body = { state: target };
        if (target === 'delivered') {
            var otp = $('otpInput').value.trim();
            if (!otp && !photoPayload) {
                toast('أدخل رمز التحقق من العميل أو صوّر الطلب عند الباب',
                      'error');
                return;
            }
            if (otp) { body.otp_code = otp; }
            if (photoPayload) { body.photo_base64 = photoPayload; }
        }
        submitStatus(body, $('stepBtn'));
    }

    function submitFailure() {
        if (busy || !order) { return; }
        submitStatus({
            state: 'failed',
            failure_reason: $('failReason').value,
            failure_notes: $('failNotes').value
        }, $('failSubmit'));
    }

    function submitStatus(body, button) {
        busy = true;
        var label = button.textContent;
        button.disabled = true;
        button.textContent = 'جاري الإرسال...';
        callApi('/api/v1/driver/order/' + order.id + '/status', body)
            .then(function () {
                $('otpInput').value = '';
                $('photoInput').value = '';
                photoPayload = null;
                $('photoLabel').classList.remove('is-set');
                $('photoLabelText').textContent = 'صوّر الطلب عند الباب';
                $('failBox').classList.add('hidden');
                $('failNotes').value = '';
                if (body.state === 'delivered') {
                    toast('تم تسليم الطلب - أحسنت', 'ok');
                } else if (body.state === 'failed') {
                    toast('سُجِّل تعذّر التسليم', 'ok');
                }
                return sync(null);
            })
            .catch(handleApiError)
            .then(function () {
                busy = false;
                button.disabled = false;
                button.textContent = label;
            });
    }

    // ==================================================================
    // التثبيت على الشاشة الرئيسية والعامل الخدمي
    // ==================================================================
    function setupInstall() {
        window.addEventListener('beforeinstallprompt', function (event) {
            event.preventDefault();
            installEvent = event;
            $('installBox').classList.remove('hidden');
        });
        $('installBtn').addEventListener('click', function () {
            if (!installEvent) { return; }
            installEvent.prompt();
            installEvent = null;
            $('installBox').classList.add('hidden');
        });
        window.addEventListener('appinstalled', function () {
            $('installBox').classList.add('hidden');
        });
    }

    function setupServiceWorker() {
        if (!('serviceWorker' in navigator)) { return; }
        // النطاق /driver يحتاج ترويسة Service-Worker-Allowed، وهي
        // تُرسَل من مسار أودو لا من ملف static.
        navigator.serviceWorker.register('/driver/sw.js', { scope: '/driver' })
            .catch(function () { /* يعمل التطبيق بلا تخزين مؤقت */ });
    }

    // ==================================================================
    // الإقلاع
    // ==================================================================
    function boot() {
        $('loginBtn').addEventListener('click', doLogin);
        $('loginPin').addEventListener('keydown', function (event) {
            if (event.key === 'Enter') { doLogin(); }
        });
        $('onlineSwitch').addEventListener('change', function (event) {
            toggleOnline(event.target.checked);
        });
        $('logoutBtn').addEventListener('click', function () {
            if (order) {
                toast('لا تخرج وعليك طلب لم يُغلق بعد', 'error');
                return;
            }
            endSession(true);
        });
        $('stepBtn').addEventListener('click', advance);
        $('failToggle').addEventListener('click', function () {
            $('failBox').classList.toggle('hidden');
        });
        $('failSubmit').addEventListener('click', submitFailure);
        $('photoInput').addEventListener('change', onPhotoChosen);

        window.addEventListener('online', function () { setNetworkBar(false); });
        window.addEventListener('offline', function () { setNetworkBar(true); });
        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState !== 'visible' || !session) { return; }
            // العودة من الخلفية: المتصفح يُوقف المؤقّتات، فنُحدّث فوراً
            // بدل إظهار طلب قديم ومؤقّت متأخّر.
            if (isOnline) { requestWakeLock(); }
            sync(null);
        });

        setupInstall();
        setupServiceWorker();

        session = loadSession();
        if (session && session.token) { startApp(); } else { showLogin(); }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();

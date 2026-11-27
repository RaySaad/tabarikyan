/* صفحة تتبع العميل: تحديث حيّ فوق صفحة مرسومة من الخادم.
 *
 * الصفحة تُرسم كاملة في الخادم أولاً - الحالة والرمز والمندوب - فمن
 * فتحها بجافاسكربت معطّلة أو شبكة ماتت بعد التحميل يرى طلبه. وهذا
 * الملف يُحدّثها فوقها كل عشر ثوان بلا إعادة تحميل.
 */
(function () {
    'use strict';

    var POLL_MS = 10000;
    var root = document.getElementById('tk-app');
    if (!root) { return; }

    var token = root.getAttribute('data-token');
    var remaining = parseInt(root.getAttribute('data-remaining'), 10) || 0;
    var isOpen = root.getAttribute('data-open') === '1';

    function $(id) { return document.getElementById(id); }

    function pad(value) { return String(value).padStart(2, '0'); }

    function renderTimer() {
        var box = $('tkTimer');
        if (!box || !isOpen) { return; }
        var late = remaining <= 0;
        var minutes = Math.floor(Math.abs(remaining) / 60);
        var seconds = Math.abs(remaining) % 60;
        box.textContent = (late && remaining < 0 ? '+' : '')
            + pad(minutes) + ':' + pad(seconds);
        var card = $('tkStatus');
        if (card) { card.classList.toggle('tk-status--late', late); }
        var hint = $('tkHint');
        if (hint && late) {
            hint.textContent = 'تأخّر قليلاً عن الوقت المستهدف - مندوبك في الطريق';
        }
    }

    function tick() {
        if (!isOpen) { return; }
        if (remaining > -5999) { remaining -= 1; }
        renderTimer();
    }

    function apply(data) {
        isOpen = !!data.is_open;
        remaining = data.remaining_seconds || 0;
        root.setAttribute('data-open', isOpen ? '1' : '0');

        var label = $('tkLabel');
        if (label) { label.textContent = data.state_label || ''; }

        // المراحل
        for (var i = 0; i < (data.steps_total || 0); i++) {
            var li = $('tkStep' + i);
            if (!li) { continue; }
            li.classList.toggle('is-done', data.step > i
                                || (data.is_delivered && data.step >= i));
            li.classList.toggle('is-current', data.step === i
                                && !data.is_delivered);
        }

        // المندوب
        var driverBox = $('tkDriver');
        if (driverBox) {
            driverBox.style.display = data.driver_name ? '' : 'none';
            var name = $('tkDriverName');
            if (name) { name.textContent = data.driver_name || ''; }
            var call = $('tkCall');
            if (call) {
                call.href = 'tel:' + (data.driver_phone || '');
                call.style.display = data.driver_phone ? '' : 'none';
            }
        }

        // الرمز: يختفي بعد التسليم - لا معنى له، ولا داعي لبقائه في
        // رابط محفوظ على جوال العميل.
        var otp = $('tkOtp');
        if (otp) {
            otp.style.display = data.delivery_otp ? '' : 'none';
            var code = $('tkOtpCode');
            if (code && data.delivery_otp) {
                code.textContent = data.delivery_otp;
            }
        }

        var timerWrap = $('tkTimerWrap');
        if (timerWrap) { timerWrap.style.display = isOpen ? '' : 'none'; }

        var status = $('tkStatus');
        if (status && data.is_delivered) {
            status.className = 'tk-card tk-status tk-status--done';
            var hint = $('tkHint');
            if (hint) { hint.textContent = 'شكراً لك'; }
        }
        renderTimer();
    }

    function poll() {
        window.fetch('/api/v1/track/' + encodeURIComponent(token), {
            headers: { 'Accept': 'application/json' }
        }).then(function (response) {
            return response.ok ? response.json() : null;
        }).then(function (data) {
            if (data && data.tracking_number) { apply(data); }
        }).catch(function () {
            /* الشبكة تذهب وتعود في الشارع: الصفحة تبقى كما هي */
        });
    }

    window.setInterval(tick, 1000);
    window.setInterval(poll, POLL_MS);
    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible') { poll(); }
    });
    renderTimer();
})();

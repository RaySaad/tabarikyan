/* شاشة "حسابي" في تطبيق المندوب: كشف الحساب وطلب السلفة.
 *
 * ملف مستقل يُضاف بوراثة القالب: لا يُعدّل جافاسكربت التطبيق الأساسي
 * ولا يعتمد على دواله. إزالة الموديول تُعيد التطبيق كما كان.
 *
 * الرابط الوحيد بينهما مفتاح الجلسة في التخزين المحلي - عقدٌ ثابت.
 */
(function () {
    'use strict';

    var SESSION_KEY = 'qd_driver_session';
    var API_ACCOUNT = '/api/v1/driver/account';
    var API_REQUEST = '/api/v1/driver/advance/request';

    var panel = null;
    var data = null;
    var busy = false;

    function token() {
        try {
            var raw = window.localStorage.getItem(SESSION_KEY);
            return raw ? (JSON.parse(raw) || {}).token : null;
        } catch (err) { return null; }
    }

    function money(value) {
        return (Number(value) || 0).toFixed(2) + ' ر.س';
    }

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) { node.className = className; }
        if (text !== undefined) { node.textContent = text; }
        return node;
    }

    function call(url, body) {
        return window.fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + token()
            },
            body: JSON.stringify(body || {})
        }).then(function (response) {
            return response.json().then(function (payload) {
                if (!response.ok) {
                    throw new Error(payload.error || 'تعذّر تنفيذ الطلب');
                }
                return payload;
            });
        });
    }

    // ==================================================================
    // البناء
    // ==================================================================
    function buildPanel() {
        panel = el('div', 'qa-panel hidden');

        var head = el('div', 'qa-head');
        var back = el('button', 'qa-back', '✕');
        back.type = 'button';
        back.addEventListener('click', close);
        head.appendChild(el('span', 'qa-title', 'حسابي'));
        head.appendChild(back);
        panel.appendChild(head);

        var body = el('div', 'qa-body');
        body.id = 'qaBody';
        panel.appendChild(body);
        document.body.appendChild(panel);
    }

    function renderBalance(account) {
        var box = el('div', 'qa-balance');
        if (!account.has_account) {
            box.classList.add('qa-balance--none');
            box.appendChild(el('div', 'qa-balance__label',
                               account.reason || 'لا حساب مرتبط'));
            return box;
        }
        var net = Number(account.net_total) || 0;
        // الإشارة كما في الكشف المطبوع: موجب = عليه للشركة.
        box.classList.add(net > 0 ? 'qa-balance--due' : 'qa-balance--credit');
        box.appendChild(el('div', 'qa-balance__label',
                           net > 0 ? 'عليك للشركة'
                                   : (net < 0 ? 'لك على الشركة' : 'حسابك صفر')));
        box.appendChild(el('div', 'qa-balance__value', money(Math.abs(net))));

        var strip = el('div', 'qa-strip');
        [['عهدة التحصيل', money(account.cod_custody)],
         ['أرباح اليوم', money(account.today_earnings)]].forEach(function (pair) {
            var cell = el('div', 'qa-strip__cell');
            cell.appendChild(el('span', 'qa-strip__label', pair[0]));
            cell.appendChild(el('strong', '', pair[1]));
            strip.appendChild(cell);
        });
        box.appendChild(strip);
        return box;
    }

    function renderLines(account) {
        var card = el('div', 'qa-card');
        card.appendChild(el('h3', 'qa-card__title', 'آخر الحركات'));
        if (!account.has_account || !account.lines.length) {
            card.appendChild(el('p', 'qa-empty', 'لا حركات بعد.'));
            return card;
        }
        account.lines.forEach(function (line) {
            var row = el('div', 'qa-line');
            var left = el('div', 'qa-line__main');
            left.appendChild(el('div', 'qa-line__desc', line.description));
            left.appendChild(el('div', 'qa-line__date', line.date));
            row.appendChild(left);
            var amount = line.debit ? line.debit : -line.credit;
            var value = el('div',
                           'qa-line__amount ' + (amount > 0 ? 'is-debit'
                                                            : 'is-credit'),
                           money(Math.abs(amount)));
            row.appendChild(value);
            card.appendChild(row);
        });
        return card;
    }

    function renderRequests(requests) {
        var card = el('div', 'qa-card');
        card.appendChild(el('h3', 'qa-card__title', 'طلبات السلف'));
        if (!requests.length) {
            card.appendChild(el('p', 'qa-empty', 'لم ترفع طلباً بعد.'));
            return card;
        }
        requests.forEach(function (req) {
            var row = el('div', 'qa-line');
            var left = el('div', 'qa-line__main');
            left.appendChild(el('div', 'qa-line__desc',
                                req.name + ' — ' + req.reason));
            left.appendChild(el('div', 'qa-line__date', req.date));
            row.appendChild(left);
            var side = el('div', 'qa-line__side');
            side.appendChild(el('div', 'qa-line__amount', money(req.amount)));
            side.appendChild(el('span',
                                'qa-badge ' + (req.is_open ? 'is-open' : ''),
                                req.state_label));
            row.appendChild(side);
            card.appendChild(row);
        });
        return card;
    }

    function renderForm(options) {
        var card = el('div', 'qa-card');
        card.appendChild(el('h3', 'qa-card__title', 'طلب سلفة'));

        if (!options.can_request) {
            card.appendChild(el('p', 'qa-empty',
                                'لا ملف موظف مرتبط بك - راجع الموارد البشرية.'));
            return card;
        }
        if (options.one_at_a_time && options.open_count) {
            card.appendChild(el('p', 'qa-note',
                                'لديك طلب لم يُحسم بعد. انتظر البتّ فيه قبل '
                                + 'طلب آخر.'));
            return card;
        }

        var amount = el('input', 'qa-field');
        amount.type = 'number';
        amount.inputMode = 'decimal';
        amount.placeholder = 'المبلغ (الحد الأعلى '
            + money(options.max_amount) + ')';

        var reason = el('select', 'qa-field');
        var blank = el('option', '', 'اختر سبب السلفة');
        blank.value = '';
        reason.appendChild(blank);
        options.reasons.forEach(function (item) {
            var opt = el('option', '', item.name);
            opt.value = item.id;
            reason.appendChild(opt);
        });

        var method = el('select', 'qa-field');
        [['bank_transfer', 'تحويل بنكي (آيبان)'],
         ['stc_pay', 'STC Pay']].forEach(function (pair) {
            var opt = el('option', '', pair[1]);
            opt.value = pair[0];
            method.appendChild(opt);
        });

        var detail = el('input', 'qa-field');
        detail.type = 'text';
        detail.dir = 'ltr';
        detail.value = options.iban || '';
        detail.placeholder = 'الآيبان';
        method.addEventListener('change', function () {
            var bank = method.value === 'bank_transfer';
            detail.placeholder = bank ? 'الآيبان' : 'رقم محفظة STC Pay';
            detail.value = bank ? (options.iban || '') : (options.phone || '');
        });

        var note = el('input', 'qa-field');
        note.type = 'text';
        note.placeholder = 'ملاحظة (اختياري)';

        var error = el('p', 'qa-error hidden');
        var submit = el('button', 'qa-submit', 'رفع الطلب');
        submit.type = 'button';
        submit.addEventListener('click', function () {
            if (busy) { return; }
            error.classList.add('hidden');
            busy = true;
            submit.disabled = true;
            submit.textContent = 'جارٍ الرفع...';
            call(API_REQUEST, {
                amount: amount.value,
                reason_id: reason.value,
                method: method.value,
                detail: detail.value,
                note: note.value
            }).then(function (payload) {
                data.requests = payload.requests;
                data.advance.open_count += 1;
                render();
                window.alert(payload.message);
            }).catch(function (err) {
                error.textContent = err.message;
                error.classList.remove('hidden');
            }).then(function () {
                busy = false;
                submit.disabled = false;
                submit.textContent = 'رفع الطلب';
            });
        });

        [amount, reason, method, detail, note, error, submit]
            .forEach(function (node) { card.appendChild(node); });
        return card;
    }

    function render() {
        var body = document.getElementById('qaBody');
        if (!body || !data) { return; }
        body.textContent = '';
        body.appendChild(renderBalance(data.account));
        body.appendChild(renderForm(data.advance));
        body.appendChild(renderRequests(data.requests || []));
        body.appendChild(renderLines(data.account));
    }

    // ==================================================================
    // الفتح والإغلاق
    // ==================================================================
    function open() {
        if (!token()) { return; }
        panel.classList.remove('hidden');
        var body = document.getElementById('qaBody');
        body.textContent = '';
        body.appendChild(el('p', 'qa-empty', 'جارٍ تحميل حسابك...'));
        call(API_ACCOUNT, {}).then(function (payload) {
            data = payload;
            render();
        }).catch(function (err) {
            body.textContent = '';
            body.appendChild(el('p', 'qa-error', err.message));
        });
    }

    function close() { panel.classList.add('hidden'); }

    function addButton() {
        var bar = document.querySelector('.qd-top__right');
        if (!bar || document.getElementById('qaOpen')) { return; }
        var button = el('button', 'qd-icon-btn', '﷼');
        button.id = 'qaOpen';
        button.type = 'button';
        button.title = 'حسابي';
        button.addEventListener('click', open);
        bar.insertBefore(button, bar.firstChild);
    }

    function boot() {
        buildPanel();
        addButton();
        // شاشة الدخول تُستبدل بالتطبيق بعد الدخول، فنُعيد المحاولة.
        var tries = 0;
        var timer = window.setInterval(function () {
            addButton();
            if (++tries > 60 || document.getElementById('qaOpen')) {
                window.clearInterval(timer);
            }
        }, 1000);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();

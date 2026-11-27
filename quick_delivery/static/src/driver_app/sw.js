/* العامل الخدمي لتطبيق المندوب.
 *
 * غرضه واحد: أن يفتح التطبيق على شبكة جوال متقطعة بدل صفحة "لا يوجد
 * اتصال" - وهذا ما يجعله تطبيقاً مُثبَّتاً لا صفحة ويب.
 *
 * ما لا يفعله: لا يُخزّن أي رد من الـAPI. بيانات الطلب والعميل
 * والمحفظة لا تُكتب في ذاكرة المتصفح الدائمة على جهاز يُسلَّم لمندوب
 * آخر غداً.
 */
'use strict';

var CACHE = 'qd-driver-v7';
var SHELL = [
    '/driver',
    '/quick_delivery/static/src/driver_app/app.css',
    '/quick_delivery/static/src/driver_app/app.js',
    '/quick_delivery/static/src/driver_app/icon-192.png',
    '/quick_delivery/static/src/driver_app/icon-512.png'
];

self.addEventListener('install', function (event) {
    event.waitUntil(
        caches.open(CACHE).then(function (cache) {
            // addAll تفشل كلها إن فشل ملف: نضيف كل ملف على حدة حتى لا
            // يُلغى التثبيت كلّه لأجل أيقونة.
            return Promise.all(SHELL.map(function (url) {
                return cache.add(new Request(url, { cache: 'reload' }))
                    .catch(function () { return null; });
            }));
        }).then(function () { return self.skipWaiting(); })
    );
});

self.addEventListener('activate', function (event) {
    event.waitUntil(
        caches.keys().then(function (names) {
            return Promise.all(names.map(function (name) {
                return name === CACHE ? null : caches.delete(name);
            }));
        }).then(function () { return self.clients.claim(); })
    );
});

self.addEventListener('fetch', function (event) {
    var request = event.request;
    if (request.method !== 'GET') { return; }

    var url = new URL(request.url);
    if (url.origin !== self.location.origin) { return; }
    // مسارات الـAPI تمرّ إلى الشبكة دائماً وبلا تخزين.
    if (url.pathname.indexOf('/api/') === 0) { return; }

    if (request.mode === 'navigate') {
        // الشبكة أولاً للصفحة: التحديثات تصل فوراً، والمخزَّن احتياط.
        event.respondWith(
            fetch(request).then(function (response) {
                var copy = response.clone();
                caches.open(CACHE).then(function (cache) {
                    cache.put('/driver', copy);
                }).catch(function () { /* ignore */ });
                return response;
            }).catch(function () {
                return caches.match('/driver').then(function (hit) {
                    return hit || new Response(
                        'التطبيق غير متاح بلا اتصال في أول تشغيل.',
                        { status: 503,
                          headers: { 'Content-Type': 'text/plain;charset=utf-8' } });
                });
            })
        );
        return;
    }

    if (url.pathname.indexOf('/quick_delivery/static/') === 0) {
        // الملفات الثابتة: المخزَّن أولاً، ثم الشبكة لتجديده.
        event.respondWith(
            caches.match(request).then(function (hit) {
                if (hit) { return hit; }
                return fetch(request).then(function (response) {
                    var copy = response.clone();
                    caches.open(CACHE).then(function (cache) {
                        cache.put(request, copy);
                    }).catch(function () { /* ignore */ });
                    return response;
                });
            })
        );
    }
});

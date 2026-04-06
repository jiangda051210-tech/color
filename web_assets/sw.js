// SENIA Elite Service Worker — 离线缓存 + 后台同步
const CACHE_NAME = 'senia-elite-v2.6';
const STATIC_ASSETS = [
  '/',
  '/manifest.json',
];

// 安装: 预缓存静态资源
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// 激活: 清理旧缓存
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// 请求: 网络优先, 回退到缓存
self.addEventListener('fetch', (event) => {
  // 只缓存 GET 请求
  if (event.request.method !== 'GET') return;
  // 不缓存 API 调用
  if (event.request.url.includes('/v1/')) return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // 成功时更新缓存
        if (response.status === 200) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});

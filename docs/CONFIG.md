# Yapılandırma

`scripts/run.py` yerel çalıştırma için gerekenleri kendisi ayarlar; bu tablo servisleri başka bir ortamda
(ör. bir sunucuda) ayrı ayrı çalıştırmak isteyenler içindir. Ayrıntı: `docs/CONTRACTS.md` §8.

| Değişken | Servis | Açıklama |
| --- | --- | --- |
| `CHESSDEX_INTERNAL_TOKEN` | API + oyun sunucusu | `/games/*` uçları için paylaşılan gizli belirteç (iki serviste aynı). `run.py` her çalıştırmada rastgele üretir. |
| `CHESSDEX_ENV=production` | API | Belirteç tanımsızsa API başlamaz. |
| `CHESSDEX_DB` | API | Oturum veritabanı (SQLite; vars. `py/data/sessions.sqlite3`; boş = yalnız bellek). |
| `CHESSDEX_PG_DSN` | API | Verilirse oturumlar PostgreSQL'de (`live_sessions`; birden fazla API örneği paylaşabilir). Önce `python -m chessdex.db_migrate`. Windows'ta yerel test sunucusu: `bash scripts/install_postgres.sh && bash scripts/install_postgres.sh start` → `postgresql://chessdex@127.0.0.1:5433/chessdex`. Testler: `CHESSDEX_TEST_PG_DSN=.../postgres`. |
| `CHESSDEX_CORS` | API | İzinli web kökenleri (virgülle). |
| `CHESSDEX_SESSION_TTL_S`, `CHESSDEX_MAX_SESSIONS` | API | Oturum temizliği (vars. 6 sa, 20 000). |
| `CHESSDEX_SESSION_RATE`, `CHESSDEX_SESSION_BURST` | API | IP başına oturum oluşturma sınırı. |
| `CHESSDEX_BANK`, `STOCKFISH_PATH` | API | Soru bankası ve Stockfish yolu (vars. `py/data/bank.jsonl`, `tools/stockfish`). |
| `CHESSDEX_HUMAN_MODEL=heuristic` | API | Maia-2 yerine basit yedek modeli kullan. |
| `CHESSDEX_TORCH_THREADS` | API | Maia-2'nin kullanacağı işlemci iş parçacığı sayısı (vars. 4). |
| `PORT`, `API_URL`, `GAME_DATA_DIR` | Oyun sunucusu | Port, API adresi, oyun anlık görüntüleri. |
| `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL` | Web | API ve WebSocket adresleri (derleme sırasında sabitlenir). |
| `NEXT_PUBLIC_SITE_URL` | Web | Yayındaki kök adres (ör. `https://...`); paylaşım önizlemesi (Open Graph görseli) için mutlak adres. |
| `CHESSDEX_PUBLIC_API_URL`, `CHESSDEX_WEB_URL` | API | Lichess OAuth dönüş adresi ve kullanıcının geri gönderileceği web adresi. |
| `CHESSDEX_LICHESS_CLIENT_ID` | API | Lichess OAuth istemci kimliği (kayıt gerekmez; vars. `chessdex`). |
| `CHESSDEX_TRUSTED_PROXIES` | API | Hız sınırı için `X-Forwarded-For`'una güvenilecek vekil IP'leri. |
| `CHESSDEX_EXPORT_SALT` | pilot dışa aktarma | Anonimleştirme tuzu (`python -m chessdex.sim.pilot_export DB OUT`). |
| `CHESSDEX_TURNSTILE_SECRET` / `NEXT_PUBLIC_TURNSTILE_SITEKEY` | API / Web | Cloudflare Turnstile bot koruması (ikisi birlikte; tanımsızsa kapalı). |
| `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE` | API | Hata izleme (tanımsızsa kapalı). |
| `CHESSDEX_LOG_FORMAT`, `CHESSDEX_LOG_LEVEL` | API | `json` (vars.) ya da düz günlük; günlük düzeyi. |
| `CHESSDEX_ITEM_CALIBRATION` | API | Pilot kalibrasyon dosyası (`python -m chessdex.sim.pilot_calibrate`; vars. `py/data/item_calibration.json`). |

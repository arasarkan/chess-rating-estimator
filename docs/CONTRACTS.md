# Arayüz Sözleşmeleri (bileşenler arası)

Bu dosya, paralel geliştirilen parçaların birbirine nasıl bağlanacağını sabitler.
Bir sözleşmeyi değiştiren, bu dosyayı da günceller.

## 0. Ortak sabitler

- θ ızgarası: `GRID = np.arange(400, 3001, 10)` → 261 nokta (Lichess rapid skalası).
  Python'da tek kaynak: `chessdex.measure.grid.GRID`.
- Olabilirlikler her zaman **log** uzayda, uzunluğu 261 olan `np.ndarray[float64]` olarak taşınır.
- Zaman: milisaniye (int). Hamleler: UCI (`e2e4`, `e7e8q`).

## 1. Python paketleri (`py/chessdex/`)

| Paket | Sahibi | Açıkta bıraktığı API |
| --- | --- | --- |
| `measure` | çekirdek | `grid.GRID`, `prior.default_prior()`, `prior.survey_prior(survey)`, `irt.Item`, `irt.log_lik_binary(item, x)`, `irt.log_lik_graded(item, k)`, `posterior.Posterior` (update/mean/sd/quantile/median), `selection.select_next(post, candidates, rng, ...)`, `stopping.should_stop(post, n, mode)`, `match.match_log_lik(moves, lam)` |
| `sim` | çekirdek | `synthetic.run(n_users, seed)` → metrik sözlüğü |
| `bank` | senaryo ajanı | `filter.iter_filtered(csv_path)`, `transforms.color_swap(fen, moves)`, `transforms.mirror(fen, moves)`, `transforms.random_transform(fen, moves, rng)`, `loader.load_items(path) -> list[BankItem]`, `scoring.score_attempt(item, given_moves, elapsed_ms)` |
| `engines` | motor ajanı | `human.HumanMoveModel` (protokol), `human.get_model()`, `stockfish.Analyzer`, `exclusion.exclusion_reason(...)` |
| `api` | çekirdek (entegrasyon) | FastAPI uygulaması: `chessdex.api.app:app` |

### 1.1 `engines.human.HumanMoveModel`

```python
class HumanMoveModel(Protocol):
    name: str
    version: str
    def move_probs(self, fen: str, elo_self: int, elo_oppo: int) -> dict[str, float]:
        """Yasal hamleler -> olasılık (toplam 1)."""
    def move_prob_grid(self, fen: str, move_uci: str, elo_oppo: int) -> np.ndarray:
        """len(GRID) uzunluklu dizi: her θ için P(move | fen, θ)."""
```

- `Maia2Model`: `maia2` paketi kuruluysa gerçek model.
- `HeuristicHumanModel`: Maia yokken kullanılan yedek; malzeme + basit arama ile
  θ'ya bağlı sıcaklıkta softmax. Belirlenimci. Sonuç kalitesi düşük, sadece akışı çalıştırmak için.
- `get_model()`: Maia varsa onu, yoksa yedeği döndürür.

### 1.2 `engines.stockfish.Analyzer`

- `Analyzer(path=None, nodes=1_000_000)`; `analyse(fen) -> {"cp": int|None, "mate": int|None, "best": uci, "win_prob": float}`.
- Her analiz öncesi `ucinewgame`, `Threads=1`, sabit `Hash`.
- Stockfish bulunamazsa `available == False` ve `analyse` `None` döner (sistem çökmez).

### 1.3 `engines.exclusion.exclusion_reason(ply, fen, move, grid_probs, eval_cp, clock_ms) -> (reason|None, weight)`

Plan "Olabilirliğe girmeyen hamleler" kuralları: `book`, `forced`, `decided` (ağırlık 0.25), `time_trouble` (ağırlık 0.3), aksi halde `(None, 1.0)`.

## 2. HTTP API (ölçüm servisi, FastAPI, port 8000)

Tümü JSON. Hata: `{"detail": "..."}`.

| Yöntem | Yol | Gövde | Yanıt |
| --- | --- | --- | --- |
| POST | `/sessions` | `{"mode": "full"\|"short", "survey": {...}?}` | `{"session_id", "estimate"}` |
| GET | `/sessions/{sid}/next-item` | – | `{"done": false, "item": {"token","fen","orientation","kind","prompt","n_moves","choices"?}}` veya `{"done": true}` |
| POST | `/sessions/{sid}/responses` | `{"token", "moves": [uci...], "elapsed_ms"}` | `{"correct", "score", "solution": [uci...], "estimate", "done"}` |
| POST | `/sessions/{sid}/game` | – | `{"game_id", "bot_level", "user_color", "time_control": {"initial_ms":600000,"increment_ms":5000}, "seed"}` |
| POST | `/games/{gid}/bot-move` | `{"fen", "ply"}` | `{"uci", "think_ms"}` |
| POST | `/games/{gid}/user-move` | `{"ply", "fen_before", "uci", "spent_ms", "clock_ms", "focus_lost"?}` | `{"ok": true}` (analiz arka planda) |
| POST | `/games/{gid}/finish` | `{"result": "1-0"\|"0-1"\|"1/2-1/2", "reason", "pgn"}` | `{"ok": true}` |
| GET | `/sessions/{sid}/report` | – | Rapor (aşağıda) |
| GET | `/health` | – | `{"ok": true, "human_model", "stockfish"}` |

`estimate`: `{"median", "lo90", "hi90", "sd", "n_items", "stage"}`.

Rapor: `{"estimate": {...}, "scales": {"lichess": {...}, "chesscom": {...}, "fide": {...}}, "subskills": {"tactics"|"endgame"|"positional"|"defense"|"time": {...}|null}, "critical_moments": [{"ply","played","eval_loss","typical"}], "flags": [...], "model_version": {...}}`.

**Ek (çok hamleli senaryolar):** `POST /responses` gövdesi `"partial": true` alabilir. Ara hamlede,
o ana kadarki hamleler doğruysa yanıt `{"continue": true, "reply": uci|null}` olur (rakibin cevabı);
yanlışsa ya da çözüm tamamlandıysa normal nihai yanıt döner. `elapsed_ms` her zaman ilk gösterimden itibaren toplam süredir.

**Ek (oyuna katılma):** web istemcisi önce `POST /sessions/{sid}/game` çağırır, sonra WS'ye
`{"t":"join","session_id","game_id","user_color","time_control"}` gönderir; oyun sunucusu ilk join'de oyunu kurar, sonrakiler yeniden bağlanmadır.

İstemci asla orijinal bulmaca kimliğini görmez: `token` sunucuda (item_id, dönüşüm) çiftine eşlenen rastgele bir dizedir.

## 3. Oyun sunucusu (Node, WebSocket, port 8080, yol `/ws`)

Saat ve hamle doğrulama burada (chess.js). Bot hamlesini ölçüm servisinden ister.

İstemci → sunucu:
- `{"t":"join","session_id","game_id"}`
- `{"t":"move","uci","ply"}`
- `{"t":"resign"}`

Sunucu → istemci:
- `{"t":"state","fen","ply","clocks":{"white":ms,"black":ms},"turn","user_color","status","moves":[uci...]}`
- `{"t":"move","uci","by":"user"|"bot","fen","clocks"}`
- `{"t":"illegal","uci"}`
- `{"t":"end","result","reason"}`

Kurallar: 10+5; saat sunucuda işler; kopmada 60 sn içinde aynı `game_id` ile `join` → kaldığı yerden; süre biterse kaybeder.
Her kullanıcı hamlesinde `POST /games/{gid}/user-move`, oyun bitince `POST /games/{gid}/finish`.
Bot sırası gelince `POST /games/{gid}/bot-move` → dönen `think_ms` kadar bekleyip hamleyi uygular (bekleme botun saatinden düşülür).

## 4. Web (Next.js, port 3000)

Ortam değişkenleri: `NEXT_PUBLIC_API_URL` (vars. `http://localhost:8000`), `NEXT_PUBLIC_WS_URL` (vars. `ws://localhost:8080/ws`).
Sayfalar: `/` (giriş + kısa anket + mod), `/test/[sid]` (senaryolar), `/play/[sid]` (maç), `/report/[sid]` (rapor).

## 5. Oyun sunucusu uygulama ayrıntıları

- `ply` 0 tabanlıdır: o ana kadar oynanmış yarım hamle sayısı (`state.ply` ile aynı); istemci `move`, `user-move` ve `bot-move` için geçerli. Uyuşmazsa `illegal` + yeni `state`.
- Ek sunucu mesajı: `{"t":"error","message"}` (bozuk JSON, join'siz mesaj, oturum uyuşmazlığı).
- `status`: `"active"` | `"ended"`. `end.reason`: `checkmate|stalemate|threefold|insufficient|fifty_move|timeout|resign|abandoned`. Süre bittiğinde rakibin mat materyali yoksa sonuç `1/2-1/2`.
- İstemci `move` mesajı isteğe bağlı `focus_lost: bool` taşır (kullanıcının sırasında sekme gizlendi / pencere odağı
  kayboldu); oyun sunucusu `user-move`'a aynen iletir, API bütünlük sinyalinde kullanır. İstemci beyanıdır: hileci
  gizleyebilir, yalnızca destekleyici sinyaldir (hiçbir zaman tek başına suçlama değildir).
- `user-move.clock_ms`: hamle anında kalan süre (artış eklenmeden önce). `state.clocks` canlıdır; `move.clocks` artış sonrasıdır.
- Saat ilk join'de başlar. Ek ortam değişkeni: `GAME_DATA_DIR` (anlık görüntüler).
- `user-move` ve `finish` çağrıları oyun başına sıralı kuyrukla, 6 deneme + üstel geri çekilme ile gider.

## 6. Ölçüm servisi uygulama ayrıntıları

- `next-item.item` ayrıca `index` ve `max_items` alanlarını içerir. Kısa modda `time_budget_ms` ve `spent_ms` de gelir:
  kısa mod, sunucuda ölçülen toplam cevap süresi bütçeyi (6,5 dk) aşınca en az 6 senaryodan sonra biter (plan ≤ 8 dk).
- Rapor ayrıca `posterior: {"grid": [...], "p": [...]}` (her 5. ızgara noktası), `match_used` ve kritik anlarda `source` (`stockfish` | `human_model`), `fen` içerir.
- Senaryo süresi sunucuda ölçülür; istemcinin `elapsed_ms` değeri yalnızca ağ gecikmesini düşmek için kullanılır (en fazla %20).
- Hata kodları: 404 bilinmeyen oturum/oyun, 409 durum hatası (geçersiz token, bitmemiş oturumda rapor, kısa modda maç).
- `responses.moves` **tam çizgidir**: oyuncu hamleleri çift indekslerde, sunucunun `reply` ile verdiği rakip cevapları tek indekslerde.
- `critical_moments[].ply` 1 tabanlıdır.
- `next-item.item.n_moves` = çözüm çizgisinin **yarım hamle** sayısı (rakip cevapları dahil); oyuncu hamlesi sayısı `ceil(n_moves/2)`.

## 7. Maç olabilirliği (Faz 2 sonrası)
- `measure.match.MoveEvidence(ply, grid_probs, weight, reason, loss_ll=None)`; `match_log_lik(moves, lam, score, bot_level, lam_loss)`.
  Hamle başına log olabilirlik = weight · (λ_Maia · log P_maia + λ_kayıp · loss_ll). Varsayılanlar `DEFAULT_LAMBDA` / `LOSS_LAMBDA`.
- `measure.loss_model.LossModel` (`py/data/loss_model.json`): kazanma olasılığı kaybı kategorisi için θ'ya bağlı olabilirlik.
- Maç analizi kayıp modeliyle aynı Stockfish derinliğinde yapılır (`loss_model.meta.bt_nodes`, şu an 100k).

## 8. Güvenlik ve işletim (üretim sertleştirmesi)
- `/games/{gid}/bot-move|user-move|finish` yalnızca oyun sunucusu içindir: `X-Internal-Token: $CHESSDEX_INTERNAL_TOKEN`
  (iki serviste aynı değer). `CHESSDEX_ENV=production` iken belirteç tanımsızsa API başlamaz; tanımsız geliştirme
  modunda uçlar korumasızdır ve `/health.internal_auth=false` döner.
- Girdi sınırları (422): `moves` en çok 20 UCI; `token` ≤ 64; `elapsed_ms` 0–3.6 M; FEN geçerli ve ≤ 100 karakter;
  `survey` yalnız `years|games_per_week|tournament`; yol kimlikleri `[A-Za-z0-9_-]{4,64}`.
- `POST /sessions` istemci IP'si başına hız sınırlı (`CHESSDEX_SESSION_RATE`/dk, `CHESSDEX_SESSION_BURST`) → 429.
- Oturumlar `CHESSDEX_SESSION_TTL_S` (vars. 6 sa) etkinliksizlikte silinir; en çok `CHESSDEX_MAX_SESSIONS` (vars. 20 000).
- CORS yalnız `GET, POST` ve `content-type`; kökenler `CHESSDEX_CORS`.
- `next-item.item.elapsed_ms`: senaryonun ilk gösteriminden beri sunucunun ölçtüğü süre (yenilemede istemci sayacı buradan sürer).
- Hız sınırı anahtarı: doğrudan eş `CHESSDEX_TRUSTED_PROXIES` listesindeyse `X-Forwarded-For` sağdan sola yürünür,
  güvenilmeyen ilk adres alınır; aksi halde başlık yok sayılır.

## 9. Harici hesap bağlama (pilot kalibrasyonu)
- `POST /sessions/{sid}/link/lichess` → `{"authorize_url"}`: Lichess OAuth2 PKCE (kayıtsız açık istemci, kapsam yok).
- `GET /oauth/lichess/callback?state&code|error` → 303 ile `CHESSDEX_WEB_URL/report/{sid}?link=ok|denied|failed`
  (bilinmeyen/süresi dolmuş state → `/?link=expired`). Belirteç saklanmaz, hemen iptal edilir; `state` tek kullanımlık, 15 dk.
- Rapor ek alanları: `external` (`platform, username, rating, rd, games, provisional, calibration_eligible,
  ineligible_reasons`) ve `comparison` (`verified_rating, difference, inside_90`).
- Kalibrasyon uygunluğu: RD < 75, ≥ 30 rapid oyun, geçici değil. Pilot veri seti: `python -m chessdex.sim.pilot_export`.
- Senaryo kalibrasyonu: `measure.calibration` (tür başına α, β, γ; sürümlü JSON); `Engine` açılışta yükler,
  `report.model_version.item_calibration` sürümü verir.
- Chess.com: `POST /sessions/{sid}/link/chesscom {"username"}` → `{"code","expires_in_s","instructions"}`;
  `POST /sessions/{sid}/link/chesscom/verify` → `{"external"}` ya da 409 (kod bulunamadı / süresi doldu / kullanıcı yok).
  `comparison.scale` = `chesscom` iken fark, tahminin Chess.com skalasındaki karşılığıyla hesaplanır.
- `POST /sessions` gövdesi `turnstile_token` alabilir; `CHESSDEX_TURNSTILE_SECRET` tanımlıysa zorunludur (geçersiz → 403).
- Her yanıtta `X-Request-ID` (istekte güvenli bir değer gelirse korunur). Yakalanmayan hata: 500
  `{"detail","request_id"}` (iç ayrıntı yok); `SENTRY_DSN` tanımlıysa olay Sentry'ye gider.

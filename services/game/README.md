# Oyun sunucusu (`services/game`)

Gerçek zamanlı maç sunucusu: WebSocket, sunucu tarafı saat (10+5), chess.js ile hamle doğrulama.
Bot hamlelerini ve analiz kayıtlarını ölçüm servisinden (FastAPI, `docs/CONTRACTS.md` bölüm 2) alır/gönderir.

## Çalıştırma

```bash
npm install
npm start          # tsx src/index.ts
npm run dev        # izleme modunda
npm test           # vitest
npm run typecheck  # tsc --noEmit
```

Ortam değişkenleri:

| Değişken | Varsayılan | Açıklama |
| --- | --- | --- |
| `PORT` | `8080` | WS adresi `ws://localhost:$PORT/ws`; `GET /health` → `{"ok": true}` |
| `API_URL` | `http://localhost:8000` | Ölçüm servisi |
| `GAME_DATA_DIR` | `services/game/data` | Oyun anlık görüntüleri (`<gid>.json`) |

## Oyuna katılma (sözleşmeye ek)

Oyun sunucusu oyunu kendisi **oluşturmaz**. Akış:

1. Web istemcisi `POST {API_URL}/sessions/{sid}/game` çağırır → `{game_id, bot_level, user_color, time_control, seed}`.
2. WS'ye bağlanır ve şunu gönderir:

```json
{"t":"join","session_id":"...","game_id":"...","user_color":"white","time_control":{"initial_ms":600000,"increment_ms":5000}}
```

- Sunucu bu `game_id`'yi tanımıyorsa oyunu bu parametrelerle **kurar** ve saat hemen başlar
  (beyazın saati işler; bot beyazsa hemen bot hamlesi istenir). `user_color` zorunlu; `time_control` yoksa 10+5.
- Tanıyorsa bu bir **yeniden bağlanmadır**: `user_color`/`time_control` yok sayılır, `session_id` eşleşmeli.
  Sözleşmedeki kısa biçim (`{"t":"join","session_id","game_id"}`) bu durumda yeterlidir.
- Her join'e yanıt olarak tam `state` gönderilir; oyun bitmişse ardından `end` da gelir.

## Mesajlar

İstemci → sunucu: `join` (yukarıda), `{"t":"move","uci","ply"}`, `{"t":"resign"}`.

Sunucu → istemci: `state`, `move`, `illegal`, `end` (sözleşmedeki biçim). Ek olarak hatalı/eksik mesajlarda
`{"t":"error","message"}` gönderilir (sözleşmeye ek).

- `ply` = o ana kadar oynanmış yarım hamle sayısı (0 tabanlı; `state.ply` ile aynı). `move.ply` verilirse
  güncel ply ile eşleşmeli, yoksa `illegal` + güncel `state` döner.
- Hamleler UCI; terfide harf zorunlu (`e7e8q`). Sıra dışı, yasadışı ya da biçimsiz hamle → `illegal` + `state`.
- `state.clocks` anlıktır (sıradaki tarafın geçen süresi düşülmüş); `move.clocks` hamle sonrası (artış eklenmiş).
- `status`: `"active"` | `"ended"`.
- `end.reason`: `checkmate`, `stalemate`, `threefold`, `insufficient`, `fifty_move`, `timeout`, `resign`, `abandoned`.
  Süre bittiğinde rakibin mat edecek malzemesi yoksa sonuç beraberliktir (`1/2-1/2`, reason `timeout`).

## Saat ve bot

- Saat tamamen sunucuda: sıra başlangıç anı tutulur, hamlede geçen süre düşülür, artış eklenir.
  Bayrak düşmesi bir zamanlayıcıyla yakalanır.
- Bot sırası: `POST /games/{gid}/bot-move {fen, ply}` → `{uci, think_ms}`. Bekleme sıra başından itibaren
  sayılır (API gecikmesi dahil) ve botun saatinden düşer; bot saatinde en az 1 sn bırakılır.
  API hatası/yasadışı yanıt → 3 kez yeniden deneme (250/500/1000 ms), sonra rastgele yasal hamle (loglanır).
- Her kullanıcı hamlesinden sonra `POST /games/{gid}/user-move {ply, fen_before, uci, spent_ms, clock_ms}`
  (`clock_ms` = hamle anında kalan süre, artış hariç). Oyun sonunda `POST /games/{gid}/finish {result, reason, pgn}`.
  Bu gönderimler oyunu bloklamaz; oyun başına sıralı bir kuyrukta, üstel geri çekilmeyle 6 kez denenir.
  İstek başına 10 sn zaman aşımı vardır.

## Kopma ve kalıcılık

- Soket kapanınca oyun ve saat işlemeye devam eder; 60 sn içinde aynı `game_id` ile join → kaldığı yerden.
  60 sn içinde hiçbir bağlantı dönmezse kullanıcı kaybeder (`abandoned`). Ölü bağlantılar 15 sn'lik ping ile yakalanır.
- Durum `GameStore` arayüzünün arkasında (şimdilik bellek içi `Map`; Redis aynı arayüzle eklenebilir).
  `SnapshotGameStore` her değişiklikte `data/<gid>.json` yazar ve açılışta hepsini yükler.
  Yeniden başlatmada kesinti süresi saatten düşülmez; sıradaki tarafın saati açılış anından devam eder ve
  60 sn terk sayacı başlar. Bildirilmemiş `finish` açılışta yeniden gönderilir.

## Yapı

- `src/index.ts` — HTTP + WS sunucusu, ortam değişkenleri.
- `src/game.ts` — `GameServer`: oyun mantığı, saat, bot akışı, bitiş. `clock` (`now()`), `random`, API istemcisi enjekte edilir.
- `src/api.ts` — `ApiClient` (fetch benzeri istemci enjekte edilir).
- `src/store.ts` — `GameStore`, `MemoryGameStore`, `SnapshotGameStore`.
- `test/game.test.ts` — vitest (sahte zamanlayıcılar + sahte API).

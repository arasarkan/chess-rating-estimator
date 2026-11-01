# apps/web — web arayüzü

Next.js 15 (App Router) + TypeScript, tahta için `chessground`, istemci tarafı yasal hamle ipuçları için `chess.js`.
Doğrulama, puanlama, saat ve tüm ölçüm hesapları sunucudadır; istemci yalnızca gösterir.

## Çalıştırma

```bash
npm install
npm run dev          # http://localhost:3000 (ölçüm servisi :8000 ve oyun sunucusu :8080 gerekir)
npm run dev:mock     # NEXT_PUBLIC_MOCK=1: sunucusuz, tarayıcı içi sahte servis
npm run build && npm start
npm run typecheck
```

Ortam değişkenleri:

| Değişken | Varsayılan | Açıklama |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Ölçüm servisi (FastAPI) |
| `NEXT_PUBLIC_WS_URL` | `ws://localhost:8080/ws` | Oyun sunucusu |
| `NEXT_PUBLIC_MOCK` | – | `1` ise `lib/mock.ts` kullanılır (yalnızca geliştirme) |

Ölçüm servisi tarayıcıdan doğrudan çağrıldığı için FastAPI tarafında `http://localhost:3000` için CORS açık olmalı.

## Yapı

```
app/layout.tsx, globals.css   ortak düzen, chessground CSS'i
app/page.tsx                  giriş: mod (Tam/Kısa) + isteğe bağlı anket → POST /sessions
app/test/[sid]/page.tsx       senaryo döngüsü (tahta / çoktan seçmeli, süre, ilerleme, anlık tahmin bandı)
app/play/[sid]/page.tsx       bota karşı maç (WS, saatler, hamle listesi, terk, otomatik yeniden bağlanma)
app/report/[sid]/page.tsx     rapor (3 skala, sonsal grafiği, alt beceriler, kritik anlar, güvenilirlik notu)
components/Board.tsx          chessground sarmalayıcı (+ terfi seçici)
components/EstimateBand.tsx   %90 aralık bandı
components/PosteriorChart.tsx medyan + %5/%95'ten yaklaşık sonsal SVG'si
lib/types.ts                  sözleşme JSON tipleri
lib/api.ts                    tipli fetch sarmalayıcı (tüm §2 uçları), mock anahtarı, sessionStorage notları
lib/mock.ts                   sahte ölçüm servisi (5 senaryo, sahte tahmin ve rapor)
lib/chess.ts                  chess.js yardımcıları (dests, UCI→SAN)
```

## Kullanılan sözleşme ekleri (docs/CONTRACTS.md §2 "Ek")

1. **Çok hamleli senaryolar — `partial`.** `n_moves > 1` olan senaryolarda (oyuncu hamleleri çift indekslerde)
   istemci her oyuncu hamlesinden sonra `POST /sessions/{sid}/responses` gönderir:
   `{"token", "moves": [o ana kadarki tüm hamleler, rakip cevapları dahil], "elapsed_ms", "partial": true}`.
   `moves.length < n_moves` iken `partial: true` eklenir; son hamlede eklenmez.
   - Doğruysa ve çözüm sürüyorsa yanıt `{"continue": true, "reply": uci|null}` olur; istemci `reply`'ı tahtada
     oynatır, `moves`'a ekler ve oyuncunun sıradaki hamlesini bekler.
   - Yanlışsa ya da çözüm tamamlandıysa normal nihai yanıt `{"correct","score","solution","estimate","done"}` döner.
   - `elapsed_ms` her zaman senaryonun ilk gösteriminden itibaren toplam süredir.
2. **Maça katılma.** İstemci önce `POST /sessions/{sid}/game` çağırır (sonuç sekme içinde `sessionStorage`'da
   saklanır; sayfa yenilenince yeni oyun açılmaz), sonra WS'ye
   `{"t":"join","session_id","game_id","user_color","time_control"}` gönderir. Her yeniden bağlanmada aynı join tekrar
   gönderilir (oyun sunucusu ilk join'de oyunu kurar, sonrakiler yeniden bağlanmadır).

## Diğer varsayımlar (sözleşmede belirsiz olanlar)

- `choices`: `string[]` (UCI) ya da `{uci, label?}[]`; seçilen şık `moves: [uci]` olarak gönderilir. Etiket yoksa SAN gösterilir.
- WS `move` mesajında `ply` = o ana kadar onaylanmış hamle sayısı (0 tabanlı; beyazın ilk hamlesi 0).
- `state.turn` `"white"|"black"` ya da `"w"|"b"` olabilir; istemci sırayı FEN'den çıkarır.
- Saat, `state.status` `"waiting"` değilse (ya da en az bir hamle yapılmışsa) ve oyun bitmemişse yerelde akar; her
  `state`/`move` mesajındaki `clocks` ile düzeltilir.
- Oyun başlangıcı standart diziliş varsayılır (hamle listesindeki SAN için).
- Rapor: `scales.*` ve `subskills.*` `{median, lo90, hi90}` içerir; `null` alt beceriler gizlenir.
  `critical_moments[].ply` 1 tabanlı; `eval_loss` ≤ 1 ise kazanma olasılığı kaybı, değilse santipiyon olarak gösterilir.
  `flags` dize kodları ya da `{code?, message?}` nesneleri olabilir; bilinen kodlar nötr Türkçe metne çevrilir.
- Rapor isteği 409/425/503 dönerse (maç analizi sürüyor) 2 sn arayla en çok 10 kez yeniden denenir.
- Çoktan seçmeli kısmi puan (`correct=false, score>0`) "Kısmen doğru" olarak gösterilir.
- Mod (`full`/`short`) `sessionStorage`'da tutulur; senaryolar bitince tam modda `/play`, kısa modda `/report`'a gidilir.

## Mock modu

`NEXT_PUBLIC_MOCK=1` iken tüm HTTP uçları `lib/mock.ts`'deki tarayıcı içi sahte servise gider (durum
`sessionStorage`'da). WS taklit edilmez: `/play` sayfası oyun sunucusunun gerektiğini söyler ve rapora bağlantı verir.

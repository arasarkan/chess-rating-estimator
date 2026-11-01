# Gerçek senaryo bankası — Lichess bulmacaları (2026-10-28)

Kaynak: `lichess_db_puzzle.csv.zst` (Last-Modified 2026-10-02, 307 MB, CC0). Yeniden üretim: `bash scripts/build_bank.sh`.

## Boru hattı
1. Sıkı filtre (plan): RD < 80, NbPlays > 1000, Popularity > 70, `Moves` 2–6 (kurulum dahil) → 36.765
2. Gevşek filtre (yalnızca eksik bantlar için): RD < 90, NbPlays > 300, Popularity > 60
3. Birleştirme: sıkı önce; gevşekten 11.465 senaryo (`meta.relaxed = true`) eklendi → **48.230**
4. Örnekleme (bant, tür) bazında; bant içi tür payları plan oranlarından (pozisyonel hariç) türetildi.
   Savunma teması oyun sonundan önce sınıflanır (aksi halde savunma %3'te kalıyordu).

## Doğrulama (`scripts/validate_bank.py`)
- Hatalı 0 · yinelenen kimlik 0 · tüm dönüşümler (renk takası/ayna) sonrası çözüm yasal ve mat korunuyor
- Tür: taktik 26.371 · oyun sonu 13.753 · savunma 8.106 · pozisyonel 0
- 400–2799 arası her 100'lük bantta 2000 senaryo; 200–399: 45, 2800–2999: 185
- b aralığı 199–2765 (b = bulmaca rating − 200; pilotta yeniden öğrenilecek)
- 1.761 oyun sonu senaryosu tablebase doğrulaması bekliyor

## Simülasyon (1000 sanal kullanıcı, θ ~ U(400, 2800))

| Ölçüt | Sentetik banka | Gerçek banka | Hedef |
| --- | --- | --- | --- |
| MAE | 48.7 | 62.9 | ≤ 150 |
| %90 kapsama | 0.914 | 0.889 | 0.87–0.93 |
| En büyük bant sapması | 27.4 | **57.8 (400–599)** | ≤ 50 |
| Ortalama senaryo | 12.2 | **19.8** | 12–20 |
| Adım süresi | 9.8 ms | 8.4 ms | p95 < 200 ms |

API gecikmesi (`scripts/bench_items.py`, 48k banka): medyan 5.4 ms, p95 10.1 ms (optimizasyon öncesi p95 836 ms).

## Açık konular
- Pozisyonel senaryo yok → oturumlar 20 senaryo sınırına dayanıyor (kısa mod ≤ 8 dk hedefi risk altında).
  Çözüm: Stockfish ile etiketlenmiş oyun pozisyonları (plan) — Stockfish kurulumu gerekli.
- 400–599 bandında +58 sapma: muhtemel neden ızgara alt sınırı (400) + N(1500, 450) önseli. İncelenmeli
  (ör. anket önseli, ızgarayı 200'e indirmek ya da uç bantta önseli genişletmek).

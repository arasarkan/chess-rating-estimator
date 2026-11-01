# Pozisyonel senaryolar — Lichess rapid oyunları + Stockfish 19 (2026-10-28)

> **DÜZELTME (2026-10-29): Bu sayfadaki "Kalibrasyon bulgusu" GEÇERSİZDİR.** Toplama kodunda `chess.pgn.read_headers`
> oyunun tamamını tükettiği için ardından okunan hamleler bir SONRAKİ oyuna aitti; pozisyonlar yanlış oyuncunun
> rating'iyle eşleşti. "Rating etkisi yok / seçim yanlılığı" sonucu bu hatanın ürünüdür. Pozisyonlar, oynanan hamleler,
> Stockfish etiketleri ve şıklar doğrudur (hepsi aynı oyundan). Düzeltilmiş okuyucu: `py/chessdex/bank/pgnstream.py`.
> Doğru verilerle tekrar (2026-10-29, 13.348 pozisyon, 4.305 pozisyonel): en iyi hamleyi bulma oranı rating'le
> düzenli artıyor — 600–899: 0.31 · 900–1199: 0.36 · 1200–1499: 0.40 · 1500–1799: 0.43 · 1800–2099: 0.53 ·
> 2100–2399: 0.57 · 2400–2699: 0.71 (lojistik w_R = 0.32; `pos_model_diagnostic.json`). Yani oyun verisi zorluk
> kalibrasyonu için KULLANILABİLİR. Bankadaki Maia-çapalı b değerleri bu veride doğrulandı: oyuncu rating'i − b farkı
> iyi hamle (≥2) oranını güçlü öngörüyor (0.35 → 0.90; olabilirlik oranı χ² = 1154). Bkz. `docs/results/backtest.md`.

Boru hattı: `py/chessdex/bank/positional.py` (collect → label → calibrate → build). Yeniden üretim: `bash scripts/build_bank.sh`.

## Veri
- Kaynak: `lichess_db_standard_rated_2026-09.pgn.zst` dosyasının ilk 800 MB'ı (29 GB'lık dosyanın akışla okunan başı)
- 1.224.366 oyun okundu → 180.206 rapid (Normal bitiş, 8–25 dk) → oyun başına 1 pozisyon, oyuncu rating bandı başına 700
- Pozisyon koşulları: 16–70. yarım hamle, kalan süre ≥ 60 sn, şah yok, ≥ 14 taş, ≥ 8 yasal hamle
- 12.739 aday; 2300 üstü bantlar seyrek (548 / 204 / 63 / 24)

## Etiketleme (Stockfish 19, 400k düğüm, tek iş parçacığı, multipv 8, 16 süreç, ~20 dk)
- Pozisyonel: |eval| ≤ 250 cp, en iyi hamle alma/şah değil, ikinci en iyi ile fark ≤ %20 kazanma olasılığı
- Puan: kayıp ≤ 0.02 → 3, ≤ 0.06 → 2, ≤ 0.15 → 1, aksi 0. Şıklar: tek 3 puanlık + en az bir ≤ 1 puanlık çeldirici;
  oyuncunun gerçek (kötü) hamlesi varsa çeldirici olarak tercih edilir (1.751 senaryoda)
- Sonuç: **2.740 senaryo**, 400–2399 arasında 200'lük bant başına ~300; şık puanları 0:1663 · 1:3285 · 2:3272 · 3:2740

## Kalibrasyon bulgusu (önemli)
Oyunlarda oyuncunun hamle kalitesi rating'le **değişmiyor** (lojistik modelde w_R ≈ −0.03; `pos_model_diagnostic.json`):

| Bant | ort. kayıp | P(≥1) | P(≥2) | P(=3) |
| --- | --- | --- | --- | --- |
| 600 | 0.070 | 0.876 | 0.682 | 0.479 |
| 1200 | 0.073 | 0.837 | 0.663 | 0.438 |
| 1800 | 0.075 | 0.837 | 0.621 | 0.434 |
| 2400 | 0.073 | 0.835 | 0.680 | 0.392 |

Neden: seçim yanlılığı — oyuncular kendi seviyesindeki rakiplerle oynadığı için önlerine gelen pozisyonlar zaten
"seviyelerine uygun". Tek bir oyun kararından mutlak zorluk ayrıştırılamaz.

Uygulanan geçici çözüm (`b_source: origin-rating-v1`, `provisional: true`): pozisyonun köken rating'i zorluğun
göstergesidir. Her bantta P(≥2) ≈ 0.66 olduğundan b = R − 115 (a = 1'de L(R − b) = 0.66).
Gerçek kalibrasyon için: Maia-2 (her θ için P(hamle | pozisyon)) veya pilot cevapları.

## Simülasyon (1000 sanal kullanıcı, 50.970 senaryoluk banka)

| Ölçüt | Yalnız bulmaca | + pozisyonel | Hedef |
| --- | --- | --- | --- |
| MAE | 62.9 | 63.4 | ≤ 150 |
| %90 kapsama | 0.889 | 0.891 | 0.87–0.93 |
| En büyük bant sapması | 57.8 | **42.7** | ≤ 50 |
| Ortalama senaryo | 19.8 | 19.85 | 12–20 |

Ortalama senaryo sayısı düşmedi: a = 1 olan senaryolarla sd < 70'e inmek bilgi kuramsal olarak ~20 senaryo gerektiriyor.
Senaryo sayısını düşürecek olanlar: pilotta öğrenilecek gerçek a değerleri ve maç sinyali.

# Pozisyonel senaryoların gerçek oyun kararlarıyla sınanması (2026-10-29)

Kod: `py/chessdex/sim/pos_freeplay.py` · ham sonuç: `pos_freeplay.json` · ayar: `py/data/item_calibration.json`.

## Veri
Bankadaki 2.408 pozisyonel senaryonun her biri, rating'i bilinen bir oyuncunun gerçek rapid oyunda o pozisyonda
verdiği karardan gelir (`meta.player_rating`, `meta.played_score`: senaryo şıklarıyla aynı 0–3 kayıp ölçeği).
Pozisyon seçimi oynanan hamleden bağımsızdır (değerlendirme ve özelliklere göre). Oyun kimliğine göre %70 eğitim
(1.684) / %30 sınama (724). Serbest oyunda şık olmadığı için tahmin payı c = 0.

## Sonuç
Sınama kümesinde ortalama log olabilirlik (yüksek = iyi):

| Model | log L |
| --- | --- |
| Bankadaki parametreler (a = 0.53, Maia-çapalı b) | −1.657 |
| Yalnız rating (senaryo bilgisi yok, 4 bant) | −1.340 |
| Tür düzeyinde yeniden uyum (α = −4919, β = 3.96, γ = 0.53) | **−1.160** |

Rating − b'ye göre "iyi hamle" (k ≥ 2) oranı, sınama kümesi:

| rating − b | gözlenen | banka öngörüsü | uyum öngörüsü |
| --- | --- | --- | --- |
| < −600 | 0.46 | 0.09 | 0.17 (gözlenen 0.25) |
| −600…−200 | 0.54 | 0.24 | 0.35 (0.50) |
| −200…200 | 0.51 | 0.50 | 0.50 (0.49) |
| 200…600 | 0.54 | 0.76 | 0.65 (0.54) |
| > 600 | 0.65 | 0.91 | 0.84 (0.74) |

(Uyum sütununda gruplar uyumlu b'ye göre oluşur; parantez içi o gruptaki gözlenen oran.)

Yorum:
- Maia-çapalı **b bilgilidir** (uyum, yalnız-rating modelini açıkça geçiyor), ama bankadaki parametreler serbest
  oyunda **rating'e duyarlılığı fazla tahmin ediyor**: banka modeli, senaryo bilgisi kullanmayan modelden bile kötü.
- Uyum, θ eğimini (γ·a) yaklaşık yarıya indiriyor. α/β'nin uç değerleri b'nin serbest oyunda daha geniş bir zorluk
  aralığına yayıldığını gösteriyor; bu kısım 4 şıklı biçime aktarılamaz (şıklar seçimi kolaylaştırır).

## Sistem etkisi (duyarlılık simülasyonu)
Gerçek banka, 500 sanal kullanıcı/koşul, yalnız senaryo aşaması. "Gerçek" cevap davranışı iki varsayımla üretildi:

| Sistemdeki pozisyonel γ | gerçek = banka: MAE / kapsama | gerçek = serbest oyun uyumu: MAE / kapsama |
| --- | --- | --- |
| 1.0 (önceki) | 71.0 / 0.894 | 86.9 / **0.794** |
| **0.5 (yeni)** | 68.1 / 0.918 | 79.8 / 0.864 |
| 0.3 | 71.5 / 0.914 | 76.9 / 0.874 |

γ = 0.5 her iki varsayımda da en az eski ayar kadar iyi: banka doğruysa bedel yok (aralık 280 → 291), serbest oyun
davranışı geçerliyse kapsama 0.79 → 0.86. Bu nedenle **pilot öncesi sağlamlık ayarı** olarak devreye alındı:
`py/data/item_calibration.json` (sürüm `robust-positional-2026-10-29`, yalnız pozisyonel a × 0.5; b değişmez).
Raporun `model_version.item_calibration` alanında görünür. Pilot kalibrasyonu (`sim.pilot_calibrate`) bu dosyanın
yerine geçer.

## Sınırlamalar
- Senaryo başına tek karar; gerçek 4 şıklı cevap davranışı ancak pilotla ölçülür.
- Duyarlılık simülasyonu maç aşamasını içermez; tam sistemde maç kanıtı aşırı güveni kısmen dengeler.

# Faz 2 — Geriye dönük test: gerçek rapid oyunlarda maç olabilirliği (2026-10-29)

Kod: `py/chessdex/sim/backtest.py` (collect → process → tune). Ayrıntılı çıktı: `docs/results/backtest_tune.json`.

## Veri
- Kaynak: `lichess_db_standard_rated_2026-08.pgn.zst` dosyasının ilk 1,5 GB'ı (4,56 M oyun okundu, 665 bin rapid).
  Pozisyonel senaryolar Eylül 2026'dan geldiği için ay ayrı (sızıntı yok).
- Seçim: rapid (8–25 dk), normal bitiş, ≥ 20 hamle; oyun başına rastgele bir taraf "kullanıcı".
- Rating kararlılığı: PGN'de RD yok → vekil K_etkin = |RatingDiff| / |sonuç − beklenen| ≤ 25 (Glicko'da K≈14 @RD50,
  ≈31 @RD75; yani kabaca RD < 65). Sürpriz < 0.15 olan oyunlar (K hesaplanamaz) alınmadı.
- 1.238 oyun (600–2599 arası her 100'lük bantta 60, 2600+ 38), 48.126 kullanıcı hamlesi.
- Hamle başına: Maia-2 ızgarası (rakip = gerçek rakip rating'i), hamle öncesi/sonrası Stockfish 19 (100k düğüm) →
  kazanma olasılığı kaybı, kitap/yasal hamle sayısı/saat.
- Bölme: %70 eğitim (866 oyun; λ, kurallar ve kayıp modeli YALNIZ burada seçilir/öğrenilir), %30 test (372 oyun).

## Önemli düzeltme: PGN okuma hatası
İlk çalıştırmada `chess.pgn.read_headers` sonrası `read_game` çağrısı bir SONRAKİ oyunu okuyordu (read_headers oyunun
tamamını tüketir) → rating'ler başka oyunların hamleleriyle eşleşti. Bu, "Maia-2 rating ayırt etmiyor" ve "Stockfish kaybı
rating'le ilişkisiz" gibi YANLIŞ sonuçlar üretti (ve pozisyonel "seçim yanlılığı" yorumunu). Düzeltme: `bank/pgnstream.py`
(oyun metni tek parça; başlık ve hamle aynı metinden) + regresyon testi; yeniden toplanan veride 839 oyun / 3.245 pozisyon
standart ayrıştırmayla birebir doğrulandı. Hatalı veri `data/raw/invalid_readheaders/` altında karantinada.

## Sinyallerin rating ile ilişkisi (doğru veri)

| Rating bandı | Ort. kayıp | Hata (>7%) | Büyük hata (>30%) | Maia: en iyi açıklayan kova |
| --- | --- | --- | --- | --- |
| 600–899 | 0.057 | 0.165 | 0.063 | 903 |
| 900–1199 | 0.051 | 0.174 | 0.048 | 903 |
| 1200–1499 | 0.051 | 0.183 | 0.046 | 1350 |
| 1500–1799 | 0.045 | 0.173 | 0.035 | 1650 |
| 1800–2099 | 0.038 | 0.155 | 0.023 | 1950 |
| 2100–2399 | 0.032 | 0.118 | 0.018 | 2137 |
| 2400–2699 | 0.020 | 0.073 | 0.008 | 2137 |

Oyun başına Maia en çok olabilirlik tahmini ile rating korelasyonu **0.69**; ortalama kayıp ile **−0.34**.

## Ayar sonuçları (TEST grubu, 372 oyun; köşeli parantez: %95 bootstrap)

| Yapılandırma | MAE | %90 kapsama | Ort. genişlik | Korelasyon |
| --- | --- | --- | --- | --- |
| Yalnız önsel N(1500, 450) | 532 [503–561] | 0.715 | 1453 | – |
| Plan varsayılanları (Maia, λ=0.5, eski kurallar) | 361 [336–387] | 0.820 | 1138 | 0.70 |
| Yalnız Maia (ayarlı, λ=0.7) | 265 [242–290] | 0.849 | 902 | 0.83 |
| Yalnız Stockfish kaybı (ayarlı) | 343 [317–367] | 0.790 | 1097 | 0.73 |
| **Maia + kayıp (seçilen)** | **250 [230–271]** | **0.849 [0.815–0.884]** | 903 | **0.86** |

Seçilen: λ_Maia = 0.5, λ_kayıp = 0.2; zorunlu hamle eşiği 0.9; kitap dışlaması KAPALI; "bitmiş pozisyon"
ağırlık düşürmesi KAPALI (ağırlık 1); zaman sıkışması < 30 sn → dışla. Tüm oyunlarda ≥ 15 analiz edilebilir hamle kaldı.
Eğitimde MAE 243 / kapsama 0.855 → testte 250 / 0.849: aşırı uyum işareti yok.

Seçilen ayarın test bantları:

| Bant | n | Sapma | MAE | Kapsama |
| --- | --- | --- | --- | --- |
| 600–899 | 45 | +318 | 318 | 0.78 |
| 900–1199 | 63 | +190 | 217 | 0.87 |
| 1200–1499 | 51 | +70 | 154 | 0.96 |
| 1500–1799 | 50 | −11 | 150 | 1.00 |
| 1800–2099 | 53 | −125 | 181 | 0.94 |
| 2100–2399 | 57 | −282 | 289 | 0.86 |
| 2400–2699 | 53 | −446 | 446 | 0.53 |

## Yorum
- Tek maç orta bölgede (1200–2099) ~150–180 Elo MAE ile iyi; referans: yayımlanmış CNN-LSTM tek oyun ~183 MAE.
- Uçlarda güçlü ortalamaya çekilme: Maia-2 903 altını / 2137 üstünü ayırt edemez ve önsel 1500 merkezlidir.
  2400+ kapsama 0.53 → planın "uçlarda aralık genişler" ilkesi sağlanmıyor. Üründe senaryolar uçları taşımalı;
  ayrıca uçlar için ek önlem gerekiyor (bkz. sonraki adımlar).
- Genel kapsama 0.85 < 0.87 hedef alt sınırı; orta bölge fazla geniş (0.94–1.00), uçlar dar.
- Üretim motoru (`api/engine.py`) ile geriye dönük test 5 gerçek oyunda birebir aynı tahmini veriyor.

## Üretime alınanlar
- `engines/exclusion.py`: USE_BOOK=False, DECIDED_WEIGHT=1.0, TIME_TROUBLE_MS=30 000, TIME_TROUBLE_WEIGHT=0.
- `measure/match.py`: LOSS_LAMBDA=0.2 ve hamle başına kayıp olabilirliği (`MoveEvidence.loss_ll`).
- `measure/loss_model.py` + `py/data/loss_model.json` (eğitim oyunlarından; 29.859 hamle).
- `api/engine.py`: maç analizi kayıp modeliyle aynı derinlikte (100k düğüm; plan 1M diyordu — kalibrasyon tutarlılığı için
  bilinçli sapma); rapor `model_version` λ'ları ve kayıp modelini içeriyor.

## Sınırlar
- Rakip burada gerçek insan; üründe bot (Maia, oyuncunun tahmini seviyesinde). Bot rakibe karşı davranış farklı olabilir.
- Kararlılık vekili kabaca; gerçek RD bilinmiyor. Kayıp modeli 100k düğüm ve Lichess rapid'e özgü.
- Senaryo + maç birleşimi henüz gerçek kullanıcılarla ölçülmedi (pilot).

## Ek: pozisyonel zorluk çapasının gerçek oyunlarla doğrulanması
Doğru toplanmış 4.305 pozisyonel oyun kararında (2026-09), oyuncunun iyi hamle (≥ 2 puan) bulması ile
"oyuncu rating'i − Maia-çapalı b₂" farkı:

| rating − b₂ | n | P(≥ 2) |
| --- | --- | --- |
| < −600 | 404 | 0.35 |
| −600…−200 | 663 | 0.53 |
| −200…200 | 911 | 0.64 |
| 200…600 | 1198 | 0.73 |
| > 600 | 1129 | 0.90 |

Lojistik modelde rating'e b₂ eklemek olabilirliği χ² = 1154 (1 sd) iyileştiriyor → çapa geçerli. Ancak eşit noktada
oran 0.50 değil 0.64 (b₂ serbest oyunda zorluğu ~150 Elo fazla tahmin ediyor) ve katsayılar gerçek zorluk dağılımının
daha geniş olduğunu gösteriyor. Sonraki adım: pozisyonel a/b'yi bu oyun kararlarıyla doğrudan kalibre etmek.

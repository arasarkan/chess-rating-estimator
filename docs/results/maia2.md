# Maia-2 entegrasyonu ve pozisyonel kalibrasyon (2026-10-28)

## Lisans
- `maia2` 0.11.0 (PyPI) ve CSSLab/maia2 deposu: **MIT** (ticari kullanım, değiştirme, dağıtım serbest; telif notu korunmalı).
- README ağırlıklar için ayrı lisans tanımlamıyor; ağırlıklar paketin resmi varlığı (Google Drive, SHA-256 doğrulamalı).
  Eğitim verisi Lichess veritabanı (CC0). Ağırlıklar ayrıca anılmadığı için lansman öncesi CSSLab'dan yazılı teyit önerilir.

## Kurulum (`scripts/setup.py`)
- maia2 0.11.0 **Python < 3.13, torch 2.8** ister; proje Python 3.14 → torch 2.15.0+cpu kuruldu, maia2
  `--no-deps --ignore-requires-python` ile eklendi. Ağırlıklar: `tools/maia2_models/rapid_model.pt` (280 MB, 23,3 M parametre).
- torch 2.15 ≠ paketin sabitlediği 2.8. Resmi `inference_each` ile karşılaştırma birebir (aşağıda), ama plan gereği
  yayından önce sabit torch sürümüyle altın testler üretilmeli.

## Adaptör doğrulaması (`py/tests/test_engines_maia.py`)
- Paketin `inference_each`'i olasılıkları 4 ondalığa yuvarlar (küçük olasılıklar 0 olur, olabilirliği bozar) ve kova başına
  çağrı ister → adaptör paketin ön işleme + modelini doğrudan, 11 kovayı tek toplu geçişte çalıştırır.
- Resmi API ile en büyük fark **5,0e-5** (4 ondalık yuvarlamanın yarı birimi); 60 pozisyon, 37'si siyah sırada.
- 2.000 gerçek rapid orta oyun hamlesinde ilk tahmin isabeti: **Maia-2 %46,9**, sezgisel yedek %32,7.
- Açık uçlu kovaların merkezi ölçüldü (Lichess 2026-09 rapid, 26.418 oyuncu-oyun): <1100 → **903**, ≥2000 → **2137**
  (önceki 1050/2050 varsayımı uçları sıkıştırıyordu).
- Gecikme: bot hamlesi medyan 12 ms, p95 19 ms (hedef < 300). Hamle analizi (Maia ızgarası + Stockfish) p95 2,1 sn
  (hedef < 5; çift Stockfish çağrısı kaldırılmadan önce 5,3 sn).

## Bulgu: Maia-2'nin pozisyon içi seviye duyarlılığı bulmacalarda zayıf

> Not (2026-10-29): Bu bölüm bulmaca verisine dayanır ve geçerlidir. Gerçek oyunlarda ise Maia-2 Elo koşullaması
> güçlü çalışıyor (oyun başına en çok olabilirlik ile rating korelasyonu 0.69; `backtest.md`). Pozisyonel b'lerin
> çapası da gerçek oyun kararlarıyla doğrulandı (χ² = 1154). Bir ara yapılan "Maia gerçek oyunlarda rating ayırt
> etmiyor" çıkarımı PGN okuma hatasından kaynaklanıyordu ve geçersizdir.
Zorluğu insan denemeleriyle ölçülmüş 3.000 Lichess bulmacasında P_maia(ilk çözüm hamlesi | θ) eğrisi:
- eğim medyan **a = 0,067** (p10 −0,12, p90 0,27), **%33'ü ters** (güçlü seviye daha az buluyor)
- ama zorluk sıralaması anlamlı: ortalama logit ile bulmaca rating'i **r = −0,44**, artık sapma **±476 Elo**

Sonuç: Maia'dan ayırt edicilik (a) alınamaz; yalnızca zorluk sıralaması alınır.

## Pozisyonel senaryolar (`py/chessdex/bank/maia_calib.py`)
1. Çeldiriciler Maia ile tasarlanır: puanı < 3 adaylardan zayıf seviyenin güçlüye göre en çok tercih ettikleri.
2. 4 şıklı seçimde (Luce) güçlüler doğru şıkkı daha AZ seçiyorsa senaryo dışlanır ("doğru" tartışmalı): 332 senaryo.
3. b: serbest yanıtta P(puan ≥ k) ortalama logit'i, bulmaca çapasıyla (rating ≈ 1612 − 236·L̄) b_k'ya çevrilir.
4. a = 0,528: ±476 Elo b belirsizliği cevap eğrisine marjinalleştirilir; c = 1/4. Senaryolar `provisional: true`.

| | Köken rating (önceki) | Maia + çapa (şimdiki) |
| --- | --- | --- |
| Senaryo | 2.740 | 2.408 |
| b dağılımı | 400–2399 düz | 1000–2199, medyan 1593 (ortalamaya çekilmiş) |
| a | 1 (varsayım) | 0,528 (belirsizlik dahil) |
| b ile köken rating korelasyonu | 1 (tanım gereği) | 0,04 |

Ara denemeler (kayıt için): Stockfish şıklarına doğrudan Maia eğrisi uydurma → yalnızca 188/2.740 senaryo a ≥ 0,25, %32'si ters.
Maia tasarımlı şıklar + a ≥ 0,25 filtresi → 635 senaryo (medyan a 0,34). Bulmaca çapası bu a'ların mutlak ölçek olmadığını
gösterince yöntem değiştirildi.

## Simülasyonlar
Senaryo simülasyonu (1000 sanal kullanıcı, 50.638 senaryoluk banka):

| Ölçüt | Köken rating bankası | Maia bankası | Hedef |
| --- | --- | --- | --- |
| MAE | 63,4 | 71,8 | ≤ 150 |
| %90 kapsama | 0,891 | 0,881 | 0,87–0,93 |
| En büyük bant sapması | 42,7 | 52,3 (400–599) | ≤ 50 |
| Ort. %90 genişlik | 250 | 280 | – |
| Ort. senaryo | 19,85 | 19,89 | 12–20 |

Simülasyon modelin doğru olduğunu varsayar; köken bankası senaryolara fazla güvendiği için yapay olarak daha iyi görünür.
Maia bankası bilinen belirsizliği taşır (daha geniş, daha dürüst aralık).

Maia'ya karşı Maia (Faz 1b, gerçek Maia-2; 60 oyun, 44'ünde ≥ 15 analiz edilebilir hamle):

| λ | MAE | sapma | %90 kapsama | %90 genişlik |
| --- | --- | --- | --- | --- |
| 0,5 | 238 | +78 | 0,909 | 1027 |
| 1,0 | 212 | +78 | 0,932 | 845 |

Hamleler burada modelden bağımsız örneklendiği için λ = 1 doğru; gerçek oyunlarda hamleler bağımlı olduğundan λ Faz 2'de
ayarlanacak. Tek maç ~±420 Elo bilgi veriyor; yayımlanmış CNN-LSTM (~183 MAE) ile aynı mertebede.
Maia 903 altını ve 2137 üstünü ayırt edemez.

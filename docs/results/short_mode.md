# Kısa mod zaman bütçesi (2026-10-29)

Plan: oturum ≤ 25 dk, **kısa mod ≤ 8 dk** (medyan). Önceki durumda durdurma kuralı modu kullanmıyordu; kısa mod da
sd < 70 ya da 20 senaryoya kadar sürüyordu (ortalama 19.8 senaryo).

## Kural
`measure/stopping.py`: kısa modda sunucunun ölçtüğü toplam cevap süresi `SHORT_BUDGET_MS` = 6,5 dk'yı aşınca, en az
`SHORT_MIN_ITEMS` = 6 senaryodan sonra durulur. Kalan ~1,5 dk senaryolar arası geri bildirim ekranları içindir. Kişi başı
süre varsayımı gerekmez: yavaş oyuncu daha az senaryo görür, aralığı da buna göre geniş kalır.
Not: senaryo başına > 65 sn harcayan çok yavaş bir oyuncuda en az 6 senaryo kuralı süreyi 8 dk'nın biraz üstüne taşıyabilir.

## Simülasyon (gerçek banka 50.638, 600 sanal kullanıcı, θ ~ U(400, 2800))
`python -m chessdex.sim.synthetic --n 600 --bank data/bank.jsonl --mode short --item-s S`

| sn/senaryo | ort. senaryo | MAE | %90 kapsama | ort. aralık genişliği | en büyük bant sapması |
| --- | --- | --- | --- | --- | --- |
| ≤ 20 | 19.8 | 69 | 0.90 | 280 | 31 |
| 30 | 13.0 | 86 | 0.91 | 354 | 46 |
| 45 | 9.0 | 107 | 0.90 | 432 | 77 |
| 60 | 7.0 | 120 | 0.91 | 516 | 122 |
| 90 | 6.0 | 143 | 0.89 | 579 | 160 |

Kapsama her hızda ~%90: aralık dürüst biçimde genişliyor. Az senaryoda uç bantlar önsele çekiliyor (bant sapması artar);
kısa mod raporu zaten "aralık daha geniş" uyarısı taşıyor. Gerçek cevap süreleri pilotta ölçülüp bütçe ayarlanmalı.

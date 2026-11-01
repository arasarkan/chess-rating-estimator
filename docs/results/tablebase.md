# Tablebase doğrulaması (2026-10-29)

Plan: "Oyun sonu: ≤ 7 taş olanlar tablebase ile doğrulanır." Uygulama: `py/chessdex/bank/tablebase.py`,
üretim hattında `scripts/build_bank.sh` adım 5 (önbellek `data/raw/tb_cache.json`, ham rapor `tablebase.json`).

## Yöntem
- Çözümdeki **her oyuncu hamlesi** için, o anda pozisyonda ≤ 7 taş varsa Lichess tablebase'i (Syzygy, herkese açık API,
  anahtarsız) sorulur. Yalnız oyun sonu türü değil, bütün türler taranır (alımlarla 7 taşa inen savunma çizgileri dahil).
- **Yanlış**: hamle teorik sonucu düşürüyor (kazanç → beraberlik/kayıp, beraberlik → kayıp) → bankadan çıkarılır.
- **Belirsiz**: beraberlik pozisyonunda başka (mat etmeyen) hamle de beraberliği koruyor → çıkarılır.
- Kazanç pozisyonunda başka kazanan hamleler sayılır ve `meta.tablebase_alternatives`'e yazılır (Lichess kuralı: daha
  yavaş kazanan hamle çözüm değildir). Mat eden alternatifler puanlamada zaten doğru sayılır.

## Sonuç (gerçek banka, 50.638 senaryo)
| | Sayı |
| --- | --- |
| Tablebase ile kontrol edilen | **2.534** (oyun sonu 974, savunma 1.560) |
| Yanlış | **0** |
| Belirsiz | **0** |
| Kontrol dışı (her adımda > 7 taş) | 48.104 |
| Sorgulanan pozisyon | 5.377 (hepsi kazanç) |

- Pozisyonların 5.375'inde tam olarak **bir** kazanan hamle var (2'sinde iki; ikisi de çözümdeki adım değil ya da mat
  alternatifi). Kontrol edilen senaryoların hiçbirinde mat etmeyen alternatif kazanç yok → puanlama belirsizliği yok.
- Plan "1.761 oyun sonu senaryosu" diyordu: bunlar oyun sonu *temalı* olanlardı; pek çoğu 7 taştan fazla. Taş sayısı
  koşulunu her çözüm adımında uygulamak kapsamı 2.534'e çıkardı.

## Mantığın sınanması
- Birim testleri (`tests/test_bank_tablebase.py`, 7): kazancı koruyan / düşüren hamle, beraberlikte belirsizlik,
  > 7 taşta ağsız atlama, alımdan sonra sonraki adımın sorgulanması, önbellek, CLI'nin çıkarma ve işaretleme davranışı.
- Mutasyon (aynı önbellekle, ağsız): 1.761 senaryonun çözümü sonucu düşüren bir hamleyle değiştirildi →
  **1.761/1.761 "yanlış"**. Yani 0 yanlış sonucu kontrolün gevşekliğinden değil, Lichess bulmacalarının zaten
  motor + tablebase ile üretilmiş olmasından kaynaklanıyor.

## Sınırlamalar
- Lichess tablebase API'sine bağlıdır (ilk çalıştırma ~10 dk, 0,25 sn aralıkla); sonraki çalıştırmalar önbellekten.
  `SKIP_TABLEBASE=1` ile atlanabilir.
- > 7 taşlı oyun sonları tablebase ile doğrulanamaz; onlar için Lichess bulmaca üreticisinin Stockfish doğrulamasına güvenilir.

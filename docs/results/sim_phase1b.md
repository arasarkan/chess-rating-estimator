# Faz 1b — "Maia'ya karşı Maia" (2026-10-28) — YEDEK MODELLE

`python -m chessdex.sim.maia_vs_maia --games 60` · insan modeli: `heuristic-h1` (Maia-2 kurulu değil)

| λ | MAE | Sapma | %90 kapsama | Ort. %90 genişlik | Ort. kullanıcı hamlesi |
| --- | --- | --- | --- | --- | --- |
| 0.5 | 262 | −106 | 0.90 | 1016 | 57 |
| 1.0 | 242 | −104 | 0.78 | 828 | 57 |

Yorum:
- Boru hattı (örnekleme → hariç tutma → ızgara olabilirliği → sonsal) uçtan uca çalışıyor.
- Sezgisel model θ'ya zayıf bağlı olduğu için tek maç ~±400 Elo bilgi veriyor; bu, Maia-2'nin yerini tutmaz.
- Hamleler burada modelden bağımsız örneklendiği için λ=1 "doğru" olmalıydı; kapsamanın düşük çıkması
  θ'nın tekdüze (önselle uyumsuz) çekilmesinden ve 60 oyunluk örnek gürültüsünden. Gerçek oyunlarda hamleler
  bağımlı olduğundan λ < 1 gerekecek (Faz 2'de ayarlanacak).
- Negatif sapma araştırılmalı (sezgisel modelin üst θ'larda ayırt edememesi olası neden).
- Maia-2 kurulduktan sonra bu simülasyon yeniden çalıştırılmalı.

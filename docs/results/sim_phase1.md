# Faz 1 — Sentetik sınav sonucu (2026-10-28)

`python -m chessdex.sim.synthetic --n 1000 --seed 1` (6000 sentetik senaryo, θ ~ U(400, 2800))

| Ölçüt | Sonuç | Hedef |
| --- | --- | --- |
| MAE | 50.5 | ≤ 150 |
| %90 kapsama | 0.878 | 0.87–0.93 |
| En büyük bant sapması | 33.7 (400–599) | ≤ 50 |
| Ortalama senaryo | 12.06 | 12–20 |
| Ortalama %90 genişlik | 198 | – |
| Senaryo adımı süresi | 26.8 ms | p95 < 200 ms |

Not: Kapsama alt sınıra yakın; durdurma kuralı sd<70 olur olmaz kestiği için hafif aşırı güven var.
Bu yalnızca matematiğin doğru olduğunu gösterir; gerçek senaryo–oyun farkı pilotta ölçülecek.

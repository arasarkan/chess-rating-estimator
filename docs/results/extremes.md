# Uç bantlarda ortalamaya çekilme (2026-10-29)

Kod: `py/chessdex/sim/extremes.py`; ayrıntılı çıktı: `docs/results/extremes_tune.json`.
Veri: Faz 2'nin 1.238 gerçek rapid oyunu (aynı %70/%30 bölme; hariç tutma kuralları Faz 2'deki gibi sabit).

## Teşhis (test, düz önselle ayrıştırma)

| Bant (tahmin − gerçek) | 600 | 900 | 1500 | 2100 | 2400 |
| --- | --- | --- | --- | --- | --- |
| Önsel N(1500, 450) + Maia + kayıp (Faz 2) | +365 | +243 | −19 | −388 | −526 |
| Düz önsel + Maia + kayıp | +199 | +183 | +121 | −68 | −119 |
| Düz önsel + yalnız Maia | +193 | +148 | +177 | −109 | −325 |
| Düz önsel + yalnız kayıp | +674 | +502 | +33 | −215 | −232 |

Kaynaklar: (1) dar önsel (en büyük pay), (2) Maia-2'nin 903 altı / 2137 üstünü ayırt edememesi,
(3) Stockfish kaybının 600–1200 arasında az ayırt edici olması (kayıp modeli kalibre: bant bazında gözlenen ve tahmin
edilen kategori oranları uyumlu).

## Aranan düzeltmeler (eğitimde birlikte seçildi; 4·4·2·3·3·3 = 768 yapılandırma)
- Maia uç kova ötesi uzatma: log-olasılık son iki kovanın eğimi × κ ile en fazla MAX_EXT Elo sürdürülür, tüm hamleler
  üzerinde yeniden normalize edilir (`engines/human.py: interp_matrix`; κ = 0 eski davranışla birebir, test edildi).
- Önsel sd ∈ {450, 600, 800}; λ_Maia ∈ {0.3, 0.5, 0.7}; λ_kayıp ∈ {0.1, 0.2, 0.3}.
- Ölçüt: MAE + 1000·|kapsama − 0.9| + 0.5·ortalama |bant sapması|.

## Sonuç — yalnız maç (test, 372 oyun)

| | MAE | %90 kapsama | 600–899 sapma / kapsama | 2400+ sapma / kapsama |
| --- | --- | --- | --- | --- |
| Faz 2 (sd 450, κ 0, λ 0.5/0.2) | 250 [230–271] | 0.849 [0.82–0.88] | +318 / 0.78 | −446 / 0.53 |
| Yalnız önsel ayarı (sd 800) | 223 [202–246] | 0.933 | +198 / 0.98 | −233 / 0.89 |
| Yalnız uzatma ayarı (sd 450) | 234 [214–254] | 0.831 | +267 / 0.76 | −384 / 0.55 |
| **Seçilen (sd 800, κ_alt 0, κ_üst 0.5, 600 Elo, λ 0.7/0.2)** | **230 [208–251]** | **0.911 [0.88–0.94]** | +199 / 0.96 | −251 / 0.81 |

İyileşmenin çoğu önselden; alt uçta Maia uzatması yardımcı olmadı (κ_alt = 0), üst uçta küçük katkı.
Tek maçla uçlar hâlâ içeri çekiliyor (±200–250) ama aralık artık bunu dürüstçe taşıyor (kapsama 0.81–0.96).

## Sonuç — tam sistem (sentetik senaryo × gerçek maç; test oyuncuları)
Her oyuncu için gerçek bankanın IRT parametreleriyle, gerçek rating'inde sentetik senaryo cevapları (üretimdeki seçim
ve durdurma) → senaryo sonsalı, ardından o oyuncunun gerçek maç olabilirliği.

| | MAE | %90 kapsama | Ort. genişlik | En büyük |bant sapması| |
| --- | --- | --- | --- | --- |
| Faz 2 ayarı | 69.7 | 0.874 | 270 | 50.8 (600–899, kapsama 0.80) |
| **Seçilen** | **62.7** | **0.911** | 271 | **23.3** (2400+) |

Planın hedefleri (MAE ≤ 150, kapsama %87–93, her bantta |sapma| ≤ 50) tam sistemde sağlanıyor. Çekince: senaryo
kısmı IRT modelinin doğru olduğunu varsayar; senaryo parametreleri (a, b) gerçek insan cevaplarıyla henüz ölçülmedi.

## Senaryo aşaması (yeni önselle; `sim.synthetic --bank`, 1000 sanal kullanıcı, θ ~ U(400, 2800))

| | MAE | Kapsama | En büyük bant sapması | Ort. senaryo |
| --- | --- | --- | --- | --- |
| sd 450 | 71.8 | 0.881 | 52.3 (400–599) | 19.9 |
| sd 800 | 69.1 | 0.905 | 29.6 (400–599) | 19.8 |

## Üretime alınanlar
- `measure/prior.py`: DEFAULT_SD = 800 (anket önseli SURVEY_SD = 700, doğrulanmadı).
- `engines/human.py`: EXTRAP_LOW = 0, EXTRAP_HIGH = 0.5, MAX_EXT = 600.
- `measure/match.py`: λ_Maia = 0.7 (λ_kayıp = 0.2 değişmedi).
- `api/engine.py`: MODEL_VERSION 0.3.0 (önsel, uzatma ve λ'lar raporda).

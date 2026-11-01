"""Durdurma kuralı: sd < 70 ise (en az 12 senaryo) ya da 20 senaryoya ulaşınca.

Kısa mod (plan: ≤ 8 dk) ek olarak zaman bütçesiyle durur: sunucuda ölçülen toplam cevap süresi SHORT_BUDGET_MS'i
aşınca (en az SHORT_MIN_ITEMS senaryodan sonra). Kalan pay senaryolar arası geri bildirim ekranlarına bırakılır.
Kişi başı süre varsayımı gerekmez; yavaş oyuncu daha az senaryo görür ve aralığı buna göre geniş kalır.
"""
MIN_ITEMS = 12
MAX_ITEMS = 20
SD_TARGET = 70.0
SHORT_BUDGET_MS = 6.5 * 60_000
SHORT_MIN_ITEMS = 6


def should_stop(post, n_items: int, mode: str = "full", elapsed_ms: int = 0) -> bool:
    if n_items >= MAX_ITEMS:
        return True
    if mode == "short" and n_items >= SHORT_MIN_ITEMS and elapsed_ms >= SHORT_BUDGET_MS:
        return True
    return n_items >= MIN_ITEMS and post.sd() < SD_TARGET

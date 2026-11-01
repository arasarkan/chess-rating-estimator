# Veritabanı (PostgreSQL)

Şema `migrations/` altında, sırayla uygulanan düz SQL dosyalarıdır (`001_init.sql`, `002_...`).
PostgreSQL 14+ ve `pgcrypto` eklentisi (UUID için) gerekir.

## Uygulama

```bash
createdb chessdex
psql -d chessdex -v ON_ERROR_STOP=1 -f db/migrations/001_init.sql
```

Docker ile:

```bash
docker run -d --name chessdex-db -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=chessdex -p 5432:5432 postgres:16
psql "postgresql://postgres:dev@localhost:5432/chessdex" -v ON_ERROR_STOP=1 -f db/migrations/001_init.sql
```

Uygulanan sürümler `schema_migrations` tablosunda tutulur. Her dosya kendi `BEGIN/COMMIT` bloğundadır;
hata olursa hiçbir değişiklik kalmaz.

## Notlar

- `item_params` sürümlüdür: parametre güncellemesi yeni `version` satırıdır. Eski satırlar silinemez,
  a/b/c değiştirilemez (tetikleyici engeller). Güncel değerler: `item_params_current` görünümü.
- `moves.maia_probs` ve `estimates.posterior`: 261 noktalık ızgara vektörleri, sıkıştırılmış `bytea`
  (ör. float32/float64 dizisi + zlib).
- Lichess bulmaca kimliği yalnızca `items.id` / `items.meta` içinde tutulur; istemciye gitmez.

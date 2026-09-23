# CS21 — Cegukan Seeker V20/21

Cari momen "cegukan" (hiccup) di transkrip YouTube. Dua bagian:

- **Engine lama** (`cs20_*.py`, `chatseeker.py`) — CLI interaktif via `cs20.sh`, tetap dipakai user.
- **`cs_core/`** — library engine baru: satu sumber scoring, keyword deklaratif
  per bahasa, matching berlapis (exact → fuzzy → phonetic), cache transcript gzip.

`cs20.sh` menu (nomor tidak berubah):

| # | Mode |
|---|---|
| 1 | ⚡ FAST SEARCH — live dashboard, unlimited channel |
| 2 | Hapus profile (ganti alias) |
| 3 | Keluar |
| 4 | 📋 Log Blocked Video |
| 5 | 📦 Index Mode — channel besar 1000+ video |
| 6 | 🔞 Recovery Age — bypass video age-restricted |
| 7 | 🎬 ChatSeeker — VTuber live-chat clip finder |
| 8 | 🚗 Auto Drive — discovery channel baru otomatis |

## Struktur

```
cs20.sh                    # menu utama (Bash)
cs20_engine.py             # engine Fast Search (live dashboard, Discord)
cs20_index_engine.py       # engine Index Mode (batch channel besar)
cs20_index_parser.py       # VTT download/parse, JSON index, manual search
cs20_age_engine.py         # bypass video age-restricted
cs20_autodrive_engine.py   # discovery channel otomatis
chatseeker.py              # engine live-chat terpisah (keyword sendiri)
bin/cs20                   # shim opsional -> python -m cs_core

cs_core/                   # library engine baru (pure stdlib, tanpa rich)
  text.py                  # normalisasi + strip tag VTT
  tokens.py                # tokenisasi satu pass (token + offset)
  languages/               # keyword = data; base/forms/spec_data/variants
  matching.py              # L1 exact → L2 fuzzy → L3 phonetic, anti-FP
  scoring.py               # SATU implementasi scoring + clustering + kasta
  transcript.py            # fetch (yt-api / yt-dlp VTT) + cache-first
  cache.py                 # cache gzip JSONL, TTL 30 hari, atomic write
  report.py                # HTML + Discord tunggal
  compat.py                # hasil baru -> dict skema lama
  config.py                # CompatMode, env flags
  diagnostics.py           # probe RapidFuzz, fallback status
  cli.py                   # CLI: analyze/search/index/age/cache

docs/                      # architecture, implementation-plan, spec-current
tests/                     # unittest (golden, parity, anti-typo, cache, ...)
tools/                     # baseline capture/compare, diff_forms, probe
```

## Instalasi (Termux / Android ARM64)

```sh
pkg install python3 yt-dlp curl
pip install youtube-transcript-api requests --break-system-packages
pip install -r requirements-termux.txt --break-system-packages   # rapidfuzz opsional
```

`requirements-min.txt` = jalur pure-stdlib: `cs_core` tetap jalan tanpa
dependency pihak ketiga (fuzzy L2 jatuh ke `difflib.SequenceMatcher`).

Verifikasi cepat:

```sh
python3 -c "import cs_core; print(cs_core.__version__)"
python3 -m cs_core --help
```

## Cara pakai (4 mode utama via `cs20.sh`)

```sh
bash inject_webhook.sh     # sekali: inject webhook Discord
bash cs20.sh               # menu interaktif
```

1. **Fast Search** (menu 1) — pantau live/semi, unlimited channel, notif Discord.
2. **Index Mode** (menu 5) — channel besar, batch + resume + manual search.
3. **Recovery Age** (menu 6) — bypass video age-restricted via cookies.
4. **Auto Drive** (menu 8) — discovery channel baru otomatis.

ChatSeeker (menu 7) engine terpisah, logika keyword sendiri — tidak diubah.

## CLI baru `cs_core`

```sh
python -m cs_core --help            # tanpa deps berat (lazy import)

python -m cs_core analyze --video gAQIEyzUHYc --lang id
python -m cs_core analyze --video gAQIEyzUHYc --lang id --json
python -m cs_core analyze --video gAQIEyzUHYc --cache-dir "$HOME/.cs20/index_cache"

python -m cs_core search --query "cegukan" --index-dir "$HOME/storage/shared/CS20_Index/channel"

python -m cs_core cache stats
python -m cs_core cache purge --video gAQIEyzUHYc
python -m cs_core cache gc --ttl-days 30

python -m cs_core index --channel <nama> --lang id   # delegasi cs20_index_engine.py
python -m cs_core age   --channel <nama> --lang id   # delegasi cs20_age_engine.py
```

`index`/`age` adalah wrapper tipis (subprocess) yang meneruskan argumen ke
engine lama. `bin/cs20` = shim opsional (sama dengan `python -m cs_core`).

## Test

```sh
python -m unittest discover -s tests -v
```

Kompatibel `pytest tests/` juga (tanpa framework tambahan).

## Catatan `cs_core`

- Engine lama TIDAK dihapus; `cs_core` berdampingan (migrasi strangler).
- Satu sumber scoring (`cs_core.scoring`) menggantikan 3 salinan E/IE/AE.
- Perilaku default `CS_COMPAT=BASELINE` supaya output identik baseline.
  Set `CS_COMPAT=IMPROVED` untuk label kasta seragam + highlight span bersih.
- Env: `CLUSTER_MODE`, `DEDUP_MODE`, `CACHE_TTL_DAYS`, `CS_ENABLE_FUZZY`
  (lihat `cs_core/config.py`).

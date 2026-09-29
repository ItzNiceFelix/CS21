# CS21 — Cegukan Seeker V21

Cari momen "cegukan" (hiccup) di transkrip YouTube, langsung dari Termux/Android.

**Satu entry point: `cs21`** (atau `bash cs20.sh`). Tanpa argumen = menu
interaktif; dengan subcommand = mode skrip/cron.

```sh
bash inject_webhook.sh      # sekali: inject webhook Discord
bash cs20.sh                # menu interaktif
```

## Menu interaktif

| # | Aksi | Catatan |
|---|---|---|
| 1 | ⚡ Scan channel | pilih dari channel tersimpan (dari checkpoint) atau ketik baru |
| 2 | 🎬 Analisa video | terima ID atau URL; hasil langsung + opsi buka di YouTube |
| 3 | 🔎 Cari di index | hasil mode Index (folder `CS20_Index`) |
| 4 | 📋 Log blocked | daftar `*_blocked.json`, scan ulang video yang kena blokir |
| 5 | 📦 Index Mode | channel besar: resume sesi, batch, cap 3 worker |
| 6 | 🔞 Recovery Age | video age-restricted (butuh cookies) |
| 7 | 💬 ChatSeeker | engine live-chat terpisah (butuh terminal interaktif) |
| 8 | 🚗 Auto Drive | discovery channel baru otomatis |
| 9 | 🧹 Cache | stats / bersihkan kedaluwarsa / hapus semua |
| d | 🩺 Doctor | preflight + `--fix` (storage, paket, cookies, webhook) |
| l | 🌐 Ganti bahasa | id/en/jp/kr/in/th |
| s | ⚙️ Setelan | fuzzy, jobs, limit, notifikasi, wake-lock |
| 0 | Keluar | |

Navigasi: **panah ↑↓ + filter + Enter** bila `prompt_toolkit` terpasang;
kalau tidak, otomatis **mode angka + tab-completion** (readline, tanpa dep).
Daftar panjang (mis. 335 channel) dipaginasi dan bisa dipersempit dengan
mengetik sebagian nama.

## CLI

```sh
cs21                          # menu interaktif
cs21 doctor                   # cek kesiapan (python, yt-dlp, cookies, storage, webhook)
cs21 doctor --fix             # perbaiki otomatis yang bisa diperbaiki

cs21 scan   --channel windahbasudara --limit 20          # plain, aman untuk cron
cs21 scan   --channel windahbasudara --limit 20 --ui     # dashboard Live
cs21 analyze --video gAQIEyzUHYc --lang id
cs21 analyze --video gAQIEyzUHYc --lang id --json        # stdout JSON murni
cs21 search --query "cegukan" --index-dir ~/storage/shared/CS20_Index
cs21 cache  stats | cs21 cache gc | cs21 cache purge --all
cs21 index --channel <nama> --total-videos 1200          # delegasi engine lama
cs21 age   --channel <nama>                              # delegasi engine lama
```

`bin/cs21` = shim agar bisa dipanggil dari folder mana pun. Semua path config
diambil dari lokasi repo (bukan CWD), jadi `cd /sdcard && cs21` tetap benar.

Catatan delegasi: `cs21 index` dan `cs21 age` meneruskan argumen apa adanya ke
engine lama. Menu selalu menambahkan `--no-prompt` supaya engine tidak bertanya
ulang (parameter sudah dikumpulkan menu). Kalau memanggil manual, tambahkan
`--no-prompt` + parameter lengkap agar cocok untuk cron:

```sh
cs21 age --channel windahbasudara --limit 5 --content-type all --no-prompt
cs21 index --channel Afandix --total-videos 1200 --total-batches 10 \
           --batches-per-run 2 --no-prompt
```

### Exit code

| Kode | Arti |
|---|---|
| 0 | sukses |
| 1 | gagal runtime (video/channel tidak ada, 0 hasil) |
| 2 | salah pakai (argumen/nilai tidak valid, mis. `--lang xx`) |
| 3 | jaringan / rate limit / diblokir YouTube |
| 4 | dependensi hilang (yt-dlp, paket python) |
| 130 | dihentikan user (Ctrl+C) |

## Struktur

```
cs20.sh                    # shim tipis -> python3 -m cs_core
bin/cs21                   # shim agar bisa dipanggil dari mana pun

cs_core/                   # CLI + menu + engine inti (pure stdlib)
  cli.py                   # argparse, exit code, stdout/stderr disiplin
  menu.py                  # menu interaktif (semua aksi + picker channel)
  tui.py                   # prompt_toolkit / readline / plain + lebar adaptif
  errors.py                # ExitCode, CsError, pesan error bahasa Indonesia
  doctor.py                # preflight Termux + --fix
  termux.py                # wake-lock, notifikasi, open-url (opsional)
  settings.py              # preferensi persisten (.cs20/settings.json)
  engine_compat.py         # normalisasi channel/bahasa untuk engine lama
  text.py tokens.py languages/ matching.py scoring.py   # inti pencocokan
  transcript.py cache.py report.py compat.py config.py diagnostics.py

cs20_engine.py             # Fast Search (dashboard live, Discord)
cs20_index_engine.py       # Index Mode (batch channel besar)
cs20_index_parser.py       # VTT download/parse, JSON index, manual search
cs20_age_engine.py         # bypass video age-restricted
cs20_autodrive_engine.py   # discovery channel otomatis
chatseeker.py              # engine live-chat terpisah (keyword sendiri)

docs/                      # architecture, implementation-plan, spec-current
tests/                     # unittest (golden, parity, anti-typo, cache, CLI, menu)
tools/                     # baseline capture/compare, diff_forms, probe
```

## Instalasi (Termux / Android ARM64)

```sh
pkg install python yt-dlp curl
pip install youtube-transcript-api requests rich --break-system-packages
pip install prompt_toolkit --break-system-packages      # opsional: menu panah
```

`requirements-min.txt` = jalur pure-stdlib (kosong; tanpa dep pihak ketiga).
`requirements-termux.txt` = `prompt_toolkit` (opsional).

**rapidfuzz tidak dipakai.** Di Termux, pip hanya menyediakan wheel murni
Python (tanpa ekstensi native) sehingga tidak mempercepat apa pun; fuzzy L2
memakai `difflib` stdlib. `cs21 doctor` memberi tahu bila rapidfuzz terpasang
tanpa ekstensi native.

Verifikasi cepat:

```sh
cs21 doctor
cs21 analyze --video gAQIEyzUHYc --lang id
```

## Cara pakai mode utama

1. **Scan channel** (menu 1) — pantau live/semi, unlimited channel, notif Discord.
2. **Index Mode** (menu 5) — channel besar, batch + resume + manual search.
3. **Recovery Age** (menu 6) — bypass video age-restricted via cookies.
4. **Auto Drive** (menu 8) — discovery channel baru otomatis.

ChatSeeker (menu 7) engine terpisah dengan logika keyword sendiri.

## Test

```sh
python -m unittest discover -s tests -v
```

Kompatibel `pytest tests/` juga (tanpa framework tambahan).

## Catatan

- Engine lama TIDAK dihapus; `cs_core` berdampingan (migrasi strangler).
- Satu sumber scoring (`cs_core.scoring`) menggantikan 3 salinan E/IE/AE.
- Perilaku default `CS_COMPAT=BASELINE` supaya output identik baseline.
  Set `CS_COMPAT=IMPROVED` untuk label kasta seragam + highlight span bersih.
- Fuzzy default `CS_FUZZY_MODE=auto`: menyala hanya bila akselerasi native ada
  (di Termux biasanya mati — 26x lebih cepat dengan hasil identik).
- Env lain: `CLUSTER_MODE`, `DEDUP_MODE`, `CACHE_TTL_DAYS`, `CS_CONFIG_DIR`
  (lihat `cs_core/config.py`).

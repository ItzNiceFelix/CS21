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
| 1 | ⚡ Scan channel | pilih satu **atau banyak** channel sekaligus (dari checkpoint) |
| 2 | 🎬 Analisa video | terima ID atau URL; hasil langsung + opsi buka di YouTube |
| 3 | 🔎 Cari di index | index rekursif + cache transkrip; Enter → buka momen |
| 4 | 📋 Log blocked | daftar `*_blocked.json`, scan ulang video yang kena blokir |
| 5 | 📦 Index Mode | channel besar: resume sesi, batch, cap 3 worker |
| 6 | 🔞 Recovery Age | video age-restricted (butuh cookies) |
| 7 | 💬 ChatSeeker | engine live-chat terpisah (butuh terminal interaktif) |
| 8 | 🚗 Auto Drive | discovery channel baru otomatis |
| 9 | 🧹 Cache | stats / bersihkan kedaluwarsa / hapus semua |
| v | 🎞️ Video terakhir | analisa ulang video yang transkripnya sudah di cache |
| r | 📄 Laporan | daftar laporan HTML, buka di aplikasi Android |
| d | 🩺 Doctor | preflight + `--fix` (storage, paket, cookies, webhook) |
| l | 🌐 Ganti bahasa | id/en/jp/kr/in (Hindi+Telugu)/th |
| s | ⚙️ Setelan | fuzzy, jobs, limit, notifikasi, wake-lock |
| 0 | Keluar | |

Header menu menampilkan lokasi data aktif (`data=… · N transkrip · N laporan`),
jadi kelihatan langsung bila cache berada di root lain.

Navigasi: **panah ↑↓ + ketik untuk memfilter + Enter** di terminal nyata —
lewat `prompt_toolkit` bila terpasang, atau pemilih raw bawaan (stdlib) bila
tidak. Mode angka + tab-completion (readline) otomatis dipakai di pipe/cron
atau bila terminal tidak mendukung pembacaan tombol mentah. Pilihan
`➕ Channel baru` selalu tampil di atas dan tidak ikut tersaring filter.
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
cs21 analyze --video "https://youtu.be/gAQIEyzUHYc?t=30" # URL apa pun diterima
cs21 analyze --video gAQIEyzUHYc --lang id --json        # stdout JSON murni
cs21 analyze --video a,b --video c --html --open         # banyak video, 1 laporan
cs21 analyze --from-file daftar.txt --lang id            # satu URL per baris
cs21 search --query "cegukan"                            # index + cache transkrip
cs21 search --query '"lagi minum" OR cegukan' --source cache
cs21 search --query cegukan --channel windahbasudara     # saring per channel
cs21 search --query cegukan --json                       # video + hit + URL per momen
cs21 report list | cs21 report open | cs21 report rm --keep 10
cs21 cache  stats | cs21 cache gc | cs21 cache purge --all
cs21 index --channel <nama> --total-videos 1200          # delegasi engine lama
cs21 age   --channel <nama>                              # delegasi engine lama
```

`--json` diterima sebelum maupun sesudah subcommand (`cache`, `report`).
Bentuk keluaran `analyze --json` mengikuti jumlah video yang **diminta**:
satu video → objek, banyak video → array (kegagalan sebagian tidak mengubah
tipe).

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

**Preflight dependensi.** `scan`, `index`, `age`, dan `auto-drive` butuh
`yt-dlp` (listing channel + unduh VTT). Bila hilang, perintah berhenti
**sebelum** engine jalan dengan exit 4 dan pesan penyebab sebenarnya —
bukan lagi "Tidak ada video ditemukan" atau "cek nama channel, koneksi".
`analyze`, `search`, `cache`, `report` tidak butuh `yt-dlp` sama sekali.

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
  paths.py                 # root data: CS_DATA_DIR > storage Android > home
  engine_compat.py         # normalisasi channel/bahasa untuk engine lama
  video.py                 # URL/ID YouTube -> ID 11 karakter (satu sumber)
  search.py                # pencarian index rekursif + cache transkrip
  reports.py               # penamaan & daftar laporan HTML
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
- Varian typo dihasilkan programatik dari `core_forms`, tapi kata nyata yang
  bisa muncul dari substitusi/fonetik diblokir lewat
  `forms.VARIANT_BLOCKLIST` (mis. en `his` dari `auto_typo("hic")`). Tanpa itu
  pronomina umum ikut dihitung CORE dan skor meledak tanpa cegukan.
- `auto_typo` tidak jalan untuk form < `MIN_AUTO_TYPO_LEN` (4): pada kata 3
  huruf satu edit sudah mengubah 33% kata (`hic` → `his`/`hec`/`hik`).
- Satu kata = satu tier. Varian generated satu tier disaring terhadap form
  deklaratif tier lain, supaya `hiccup` tidak dihitung CORE + TYPO sekaligus.
- Boundary regex per aksara: Latin `\b`; Devanagari/Telugu lookaround rentang
  (`\b` Python tidak cocok pada form berakhiran matra); JP/KR/Thai tanpa
  boundary karena partikel menempel pada kata.
- Lapisan fonetik L3 hanya aktif untuk `id` (`matching.PHONETIC_LANGS`):
  aturan `c→s`/`k→g` diturunkan dari ejaan Indonesia dan merusak bahasa lain.
- `AnalysisResult.mean_similarity` + `Hit.similarity` melaporkan rasio
  kemiripan nyata per hit (1.0 = exact, <1.0 = fuzzy), bukan cuma gerbang.
- Env lain: `CLUSTER_MODE`, `DEDUP_MODE`, `CACHE_TTL_DAYS`, `CS_CONFIG_DIR`
  (lihat `cs_core/config.py`).
- **Lokasi data** (`cs_core/paths.py`): root primer =
  `CS_DATA_DIR` > `/storage/emulated/0/CS20_Index` > `~/.cs20/index_cache`.
  Penulisan selalu ke primer, **pembacaan** mencakup semua root yang ada —
  cache lama di home PRoot/Termux tidak hilang saat primer berpindah.
  `doctor` menampilkan daftar root; menu menampilkannya di header.
- **Laporan HTML** disimpan di `/storage/emulated/0/CS20_Laporan/`
  (`laporan_<label>_<ddmmyyyy_hhmm>.html`) supaya terlihat di file manager
  Android. Kelola dengan `cs21 report list|open|rm` atau menu `r`.
  Engine lama memakai folder yang sama (bukan lagi `.cs20/` yang tersembunyi).
- **Skor vs konfidensi**: `persentase` = skor rumus kasta; `mean_similarity`
  = rata-rata rasio kemiripan CORE (1.0 = semua hit exact). Laporan HTML
  menampilkan keduanya terpisah dan menandai hit fuzzy dengan `~N%`.

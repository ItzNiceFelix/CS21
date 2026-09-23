# Fase 0 — Baseline Capture di Termux

Tujuan: merekam input segmen mentah + output 4 engine (E/IE/AE/CS) untuk
beberapa video nyata, supaya refactor `cs_core` (Fase 1+) bisa divalidasi
byte-for-byte terhadap perilaku lama.

Semua perintah dijalankan **di Termux** (punya `yt-dlp`, `youtube-transcript-api`,
`rich`). Skrip di `tools/` sengaja mengimpor dependency berat secara lazy, jadi
`--help` / `--dry-run` tetap jalan tanpa deps itu.

---

## 1. Instalasi

```bash
pip install youtube-transcript-api requests yt-dlp rich --break-system-packages
# opsional, hanya bila mau merekam engine CS (chat):
pip install yt-dlp --break-system-packages   # sudah di atas, yt-dlp dipakai chatseeker
```

## 2. Masuk ke repo

```bash
cd ~/nerite
```

## 3. Rekam baseline (channel id)

```bash
python3 tools/baseline_capture.py --channel "<CHANNEL>" --lang id --limit 20 \
  --out tests/fixtures/baseline_<channel>_id.json

python3 tools/baseline_capture.py --channel "<CHANNEL2>" --lang en --limit 20 \
  --out tests/fixtures/baseline_<channel2>_en.json
```

`<CHANNEL>` boleh handle (`@windahbasudara` atau `windahbasudara`),
channel_id mentah (`UCxxxxxxxxxxxxxxxxxxxxxxxx`), atau URL penuh.

## 4. Uji cepat sebelum kirim

```bash
# --help harus exit 0 tanpa crash
python3 tools/baseline_capture.py --help

# --dry-run: tanpa fetch berat, hanya tulis meta + videos kosong
python3 tools/baseline_capture.py --dry-run --channel "<CHANNEL>" \
  --out /tmp/dry.json

# self-compare: WAJIB exit 0 (identik)
python3 tools/baseline_compare.py \
  tests/fixtures/baseline_<channel>_id.json \
  tests/fixtures/baseline_<channel>_id.json
echo "exit=$? (harus 0)"
```

## 5. (Opsional) Rekam engine CS / chat

Bila sudah punya file chat `chat_<video_id>.live_chat.json` (hasil chatseeker),
letakkan semuanya di satu folder lalu:

```bash
python3 tools/baseline_capture.py --channel "<CHANNEL>" --lang id --limit 20 \
  --engines e,ie,ae,cs --chat-dir /path/ke/folder/chat \
  --out tests/fixtures/baseline_<channel>_id.json
```

Bila `--chat-dir` tak diisi, engine `cs` otomatis di-`skipped` (bukan error).

## 6. (Opsional) Probe scoring murni

Rekam rumus cluster+score+kasta tanpa fetch transkrip:

```bash
python3 tools/fixtures_synthetic.py --out tools/synthetic_segments.json
python3 tools/pure_scoring_probe.py --lang id \
  --segments tools/synthetic_segments.json --out tools/probe_id.json
```

## 7. Yang harus dikirim balik

Kirim **file JSON** hasil capture:

```
tests/fixtures/baseline_<channel>_id.json
tests/fixtures/baseline_<channel2>_en.json
```

Plus, bila dijalankan, `tools/probe_id.json`.

Format tiap file:

```json
{
  "meta": {
    "channel": "...", "lang": "id", "limit": 20,
    "engines": ["ae", "cs", "e", "ie"],
    "dedup_mode": "baseline",
    "cluster_mode": "baseline",
    "captured_at": "2026-...", "source": "yt-api",
    "tool": "baseline_capture.py"
  },
  "videos": [
    {
      "video_id": "...",
      "source": "yt-api",
      "segments_raw": [{"text": "...", "start": 0.0, "duration": 1.5}],
      "engines": {"e": {...}, "ie": {...}, "ae": {...}, "cs": {...}}
    }
  ]
}
```

Catatan:
- `dedup_mode` & `cluster_mode` selalu `"baseline"` (P8/M9 belum diaktifkan).
- `source` per-video: `yt-api` (dari youtube-transcript-api) atau `none`.
- `engines.*.skipped` muncul bila segmen/file chat tak tersedia — itu normal.
- `engines.*.error` muncul bila import/scoring gagal — sertakan apa adanya saat
  kirim balik.

## 8. Gate F0

- >=2 fixture (id + en) ada.
- `baseline_compare.py <file> <file>` → exit 0 (self-compare identik).

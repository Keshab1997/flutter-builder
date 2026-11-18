"""Offline behaviour tests for the screenshot capture scripts.

The .cjs helpers are exercised through `node -e` requiring
scripts/capture-pages.cjs (the exports exist exactly so this needs no
browser), and the shell scripts are exercised as subprocesses. No network,
no Playwright download, no Chromium launch:

  * PNG decoding: valid solid vs multi-colour PNGs, every PNG filter type,
    truncated/corrupt PNGs returning null instead of throwing;
  * parseArgs validation (bad numbers, bad viewports, bad strategy);
  * hash vs path URL building and the poll frame-selection helper;
  * colliding route slug disambiguation;
  * manifest-summary.sh: 4/6 columns, pipe in route, non-numeric size,
    missing file;
  * capture-screenshots.sh up-front argument validation (exit 2).

The node checks are deliberately grouped into a few processes: node starts
in milliseconds, but this kind of sandbox can hit transient CPU spikes, and
every extra launch multiplies the chance one of them lands on one.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "scripts" / "capture-pages.cjs"
SUMMARY = ROOT / "scripts" / "manifest-summary.sh"
CAPTURE = ROOT / "scripts" / "capture-screenshots.sh"

# JS helpers for building real PNGs in-process (node's zlib for the IDAT,
# a tiny CRC32 for the chunk wrappers). `filters` picks the PNG row filter
# per row so every filter type (0-4) can be round-tripped through pngStats.
PNG_JS = r"""
const zlib = require('zlib');
const CRC_TABLE = (() => {
  const t = new Int32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
    t[n] = c;
  }
  return t;
})();
function crc32(buf) {
  let c = 0xFFFFFFFF;
  for (let i = 0; i < buf.length; i += 1) c = CRC_TABLE[(c ^ buf[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}
function chunk(type, data) {
  const out = Buffer.alloc(12 + data.length);
  out.writeUInt32BE(data.length, 0);
  out.write(type, 4, 'latin1');
  data.copy(out, 8);
  out.writeUInt32BE(crc32(out.subarray(4, 8 + data.length)), 8 + data.length);
  return out;
}
function ihdr(width, height, channels) {
  const b = Buffer.alloc(13);
  b.writeUInt32BE(width, 0);
  b.writeUInt32BE(height, 4);
  b[8] = 8;
  b[9] = { 1: 0, 2: 4, 3: 2, 4: 6 }[channels];
  return b;
}
const PNG_SIG = Buffer.from([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]);
function makePng(width, height, pixels, channels, filters) {
  channels = channels || 3;
  filters = filters || [0];
  const stride = width * channels;
  let upRow = null;
  const rows = [];
  for (let y = 0; y < height; y += 1) {
    const filter = filters[y % filters.length];
    const orig = Buffer.from(pixels.subarray(y * stride, (y + 1) * stride));
    const row = Buffer.alloc(1 + stride);
    row[0] = filter;
    for (let x = 0; x < stride; x += 1) {
      const left = x >= channels ? orig[x - channels] : 0;
      const up = upRow ? upRow[x] : 0;
      const upLeft = upRow && x >= channels ? upRow[x - channels] : 0;
      let pred = 0;
      if (filter === 1) pred = left;
      else if (filter === 2) pred = up;
      else if (filter === 3) pred = (left + up) >> 1;
      else if (filter === 4) {
        const p = left + up - upLeft;
        const pa = Math.abs(p - left);
        const pb = Math.abs(p - up);
        const pc = Math.abs(p - upLeft);
        pred = (pa <= pb && pa <= pc) ? left : (pb <= pc ? up : upLeft);
      }
      row[1 + x] = (orig[x] - pred) & 0xFF;
    }
    rows.push(row);
    upRow = orig;
  }
  return Buffer.concat([
    PNG_SIG,
    chunk('IHDR', ihdr(width, height, channels)),
    chunk('IDAT', zlib.deflateSync(Buffer.concat(rows))),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}
// 16x16 of 4x4 colour blocks: pngStats samples (0,0),(4,0),(0,4),(4,4), which
// all land in different blocks, so a correct decoder sees exactly 4 colours.
function colouredPixels() {
  const cols = [[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 0]];
  const px = Buffer.alloc(16 * 16 * 3);
  for (let y = 0; y < 16; y += 1) {
    for (let x = 0; x < 16; x += 1) {
      const c = cols[((x >> 2) & 1) + 2 * ((y >> 2) & 1)];
      const off = (y * 16 + x) * 3;
      px[off] = c[0];
      px[off + 1] = c[1];
      px[off + 2] = c[2];
    }
  }
  return px;
}
"""


class CapturePagesNodeTests(unittest.TestCase):
    """capture-pages.cjs unit checks through node (no browser)."""

    @staticmethod
    def require_module() -> str:
        return f"const m = require({json.dumps(str(PAGES))});"

    def assert_node_ok(self, body: str) -> None:
        code = f"const assert = require('assert');\n{PNG_JS}\n{self.require_module()}\n{body}\n"
        done = None
        for _attempt in range(3):
            try:
                done = subprocess.run(
                    ["node", "-e", code], capture_output=True, text=True,
                    check=False, timeout=300)
            except subprocess.TimeoutExpired:
                # This sandbox gets transient CPU spikes that starve a node
                # process for minutes; the checks themselves run in
                # milliseconds, so a hang is retried. A real assertion
                # failure exits non-zero and is not retried.
                done = None
            else:
                break
        self.assertIsNotNone(done, "node process timed out on every attempt")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_png_decoder(self) -> None:
        self.assert_node_ok(r"""
// Valid: a solid fill is one colour and blank.
const solid = makePng(16, 16, Buffer.alloc(16 * 16 * 3, 255), 3, [0]);
const s = m.pngStats(solid);
assert.strictEqual(s.width, 16);
assert.strictEqual(s.height, 16);
assert.strictEqual(s.distinct, 1);
assert.strictEqual(s.topShare, 1);
assert.ok(m.looksBlank(s), 'a flat fill is blank');
// Valid: four sampled colours is not blank.
const multi = m.pngStats(makePng(16, 16, colouredPixels(), 3, [0]));
assert.strictEqual(multi.distinct, 4);
assert.ok(!m.looksBlank(multi), 'four colours is not blank');
// RGBA and a 1x1 shot decode too.
const rgba = m.pngStats(makePng(16, 16, Buffer.alloc(16 * 16 * 4, 200), 4, [0]));
assert.strictEqual(rgba.width, 16);
assert.strictEqual(rgba.height, 16);
const one = m.pngStats(makePng(1, 1, Buffer.from([10, 20, 30, 255]), 4, [0]));
assert.strictEqual(one.width, 1);
assert.strictEqual(one.height, 1);
assert.strictEqual(one.distinct, 1);
// Every PNG row filter must round-trip to the same picture.
const px = colouredPixels();
const expected = m.pngStats(makePng(16, 16, px, 3, [0]));
for (const f of [1, 2, 3, 4]) {
  const st = m.pngStats(makePng(16, 16, px, 3, [f]));
  assert.ok(st, 'filter ' + f + ' must decode');
  assert.strictEqual(st.width, expected.width, 'filter ' + f);
  assert.strictEqual(st.height, expected.height, 'filter ' + f);
  assert.strictEqual(st.distinct, expected.distinct, 'filter ' + f);
}
const mixed = m.pngStats(makePng(
  16, 16, px, 3, [0, 1, 2, 3, 4, 0, 1, 2, 3, 4, 0, 1, 2, 3, 4, 0]));
assert.strictEqual(mixed.distinct, expected.distinct);
// Truncation at every interesting point returns null, never throws.
const png = makePng(16, 16, Buffer.alloc(16 * 16 * 3, 255), 3, [0]);
for (const cut of [8, 15, 29, 33, 40, png.length - 3, png.length - 1]) {
  assert.strictEqual(m.pngStats(png.subarray(0, cut)), null, 'cut at ' + cut);
}
assert.strictEqual(m.pngStats(Buffer.from('definitely not a png')), null);
assert.strictEqual(m.pngStats(Buffer.alloc(0)), null);
// Corrupt IDAT: valid chunk wrapper, zlib garbage inside.
const bad = Buffer.concat([
  PNG_SIG,
  chunk('IHDR', ihdr(16, 16, 3)),
  chunk('IDAT', Buffer.from([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])),
  chunk('IEND', Buffer.alloc(0)),
]);
assert.strictEqual(m.pngStats(bad), null);
// Truncated inflated buffer: valid zlib, far too few bytes for 16x16x3.
const shortRaw = Buffer.concat([
  PNG_SIG,
  chunk('IHDR', ihdr(16, 16, 3)),
  chunk('IDAT', zlib.deflateSync(Buffer.alloc(4 * 8))),
  chunk('IEND', Buffer.alloc(0)),
]);
assert.strictEqual(m.pngStats(shortRaw), null);
// Unknown row filter type.
const rows = [];
for (let y = 0; y < 16; y += 1) {
  const r = Buffer.alloc(1 + 16 * 3);
  r[0] = 7;
  rows.push(r);
}
const unknown = Buffer.concat([
  PNG_SIG,
  chunk('IHDR', ihdr(16, 16, 3)),
  chunk('IDAT', zlib.deflateSync(Buffer.concat(rows))),
  chunk('IEND', Buffer.alloc(0)),
]);
assert.strictEqual(m.pngStats(unknown), null);
// Short IHDR.
const shortIhdr = Buffer.concat([
  PNG_SIG,
  chunk('IHDR', Buffer.alloc(10)),
  chunk('IEND', Buffer.alloc(0)),
]);
assert.strictEqual(m.pngStats(shortIhdr), null);
""")

    def test_parse_args(self) -> None:
        self.assert_node_ok(r"""
function expectBad(argv, needle) {
  let threw = false;
  try {
    m.parseArgs(argv);
  } catch (error) {
    threw = true;
    assert.ok(String(error.message).includes(needle),
      'message "' + error.message + '" lacks "' + needle + '"');
  }
  assert.ok(threw, 'parseArgs accepted ' + JSON.stringify(argv));
}
// Defaults survive a bare call.
const d = m.parseArgs([]);
assert.strictEqual(d.waitMs, 12000);
assert.strictEqual(d.maxWaitMs, 60000);
assert.strictEqual(d.minBytes, 5 * 1024);
assert.strictEqual(d.urlStrategy, 'hash');
assert.strictEqual(d.url, 'http://127.0.0.1:8080');
// Valid values, including zero (legal) for the numeric flags.
const v = m.parseArgs(['--wait-ms', '1000', '--max-wait-ms', '0', '--min-bytes', '0',
  '--viewports', '390x844,768x1024', '--url-strategy', 'path', '--selector', 'flutter-view']);
assert.strictEqual(v.waitMs, 1000);
assert.strictEqual(v.maxWaitMs, 0);
assert.strictEqual(v.minBytes, 0);
assert.strictEqual(v.viewports, '390x844,768x1024');
assert.strictEqual(v.urlStrategy, 'path');
assert.strictEqual(v.selector, 'flutter-view');
// Bad numbers.
expectBad(['--wait-ms', '-5'], 'wait-ms');
expectBad(['--wait-ms', 'abc'], 'wait-ms');
expectBad(['--wait-ms', ''], 'wait-ms');
expectBad(['--max-wait-ms', '-1'], 'max-wait-ms');
expectBad(['--min-bytes', '-3'], 'min-bytes');
expectBad(['--min-bytes', '1e400'], 'min-bytes');
// Bad viewports: zero, missing half, sign, space.
expectBad(['--viewports', '0x844'], 'viewport');
expectBad(['--viewports', '390x0'], 'viewport');
expectBad(['--viewports', '390'], 'viewport');
expectBad(['--viewports', '-5x10'], 'viewport');
expectBad(['--viewports', '12x'], 'viewport');
expectBad(['--viewports', '390 x 844'], 'viewport');
// Bad strategy, unknown option, missing value.
expectBad(['--url-strategy', 'bogus'], 'url-strategy');
expectBad(['--nope'], 'unknown option');
expectBad(['--wait-ms'], 'needs a value');
""")

    def test_url_building_and_helpers(self) -> None:
        self.assert_node_ok(r"""
const base = 'http://127.0.0.1:8080';
// hash (the default): the route goes into the fragment
assert.strictEqual(m.pageUrl(base, '/', 'hash'), base + '/#/');
assert.strictEqual(m.pageUrl(base + '/', '/settings', 'hash'), base + '/#/settings');
assert.strictEqual(m.pageUrl(base, '#/settings', 'hash'), base + '/#/settings');
// fragment() keeps the original contract: a bare route keeps no extra slash
assert.strictEqual(m.pageUrl(base, 'settings', 'hash'), base + '/#settings');
assert.strictEqual(m.pageUrl(base, '/a'), base + '/#/a'); // strategy defaults to hash
// path: the route is served at <base><route>
assert.strictEqual(m.pageUrl(base + '/', '/settings', 'path'), base + '/settings');
assert.strictEqual(m.pageUrl(base, 'settings', 'path'), base + '/settings');
assert.strictEqual(m.pageUrl(base, '', 'path'), base + '/');
assert.strictEqual(m.pageUrl(base, '/', 'path'), base + '/');
assert.strictEqual(m.pageUrl(base + '//', '/a/b', 'path'), base + '/a/b');
// slug and fragment keep their contract
assert.strictEqual(m.slug('/a/b'), 'a-b');
assert.strictEqual(m.slug('/'), 'home');
assert.strictEqual(m.fragment(''), '#/');
assert.strictEqual(m.fragment('/'), '#/');
assert.strictEqual(m.fragment('#/a'), '#/a');
assert.strictEqual(m.fragment('a'), '#a');
// Colliding slugs: /a/b and /a-b must not overwrite each other.
const used = new Set();
assert.strictEqual(m.shotFileBase('/a/b', 390, 844, used), 'a-b-390x844');
assert.strictEqual(m.shotFileBase('/a-b', 390, 844, used), 'a-b-390x844-2');
assert.strictEqual(m.shotFileBase('/a/b', 390, 844, used), 'a-b-390x844-3');
assert.strictEqual(m.shotFileBase('/a/b', 768, 1024, used), 'a-b-768x1024');
assert.strictEqual(m.shotFileBase('/', 390, 844, new Set()), 'home-390x844');
// Poll frame selection: content wins even at a smaller size; while blank,
// the largest buffer is kept; undecodable frames never claim content.
const frame = (len, stats) => ({ buffer: Buffer.alloc(len), stats });
let r = m.pickBestFrame(frame(3000, { distinct: 1, topShare: 1 }), null);
assert.strictEqual(r.done, false);
r = m.pickBestFrame(frame(2800, { distinct: 40, topShare: 0.1 }), r.best);
assert.strictEqual(r.done, true);
assert.strictEqual(r.best.buffer.length, 2800);
r = m.pickBestFrame(frame(500, { distinct: 40, topShare: 0.1 }), null);
assert.strictEqual(r.done, true);
r = m.pickBestFrame(frame(100, { distinct: 1, topShare: 1 }), null);
assert.strictEqual(r.done, false);
r = m.pickBestFrame(frame(150, { distinct: 2, topShare: 0.9 }), r.best);
assert.strictEqual(r.done, false);
assert.strictEqual(r.best.buffer.length, 150);
r = m.pickBestFrame(frame(120, { distinct: 1, topShare: 1 }), r.best);
assert.strictEqual(r.done, false);
assert.strictEqual(r.best.buffer.length, 150);
r = m.pickBestFrame({ buffer: Buffer.alloc(999), stats: null }, null);
assert.strictEqual(r.done, false);
""")


class ManifestSummaryBehaviourTests(unittest.TestCase):
    """manifest-summary.sh against hand-made manifests."""

    def run_script(self, content: str, *extra: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.tsv"
            manifest.write_text(content, encoding="utf-8")
            return subprocess.run(
                ["bash", str(SUMMARY), str(manifest), *extra],
                capture_output=True, text=True, check=False, timeout=60)

    def test_six_column_manifest(self) -> None:
        done = self.run_script("home\t/\t390x844\t67739\t1491\t0.867\n")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("| `home.png` | `/` | 390x844 | 66 KB | 1491 |", done.stdout)

    def test_four_column_manifest(self) -> None:
        done = self.run_script("home\t/\t390x844\t67739\n")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("| `home.png` | `/` | 390x844 | 66 KB |", done.stdout)

    def test_pipe_in_route_does_not_break_the_table(self) -> None:
        done = self.run_script("home\t/a|b\t390x844\t67739\t1491\t0.867\n")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("`/a\\|b`", done.stdout)
        self.assertNotIn("`/a|b`", done.stdout)
        # The escaped row still has exactly the five real columns (the
        # backslash-escaped pipe is not a separator).
        row = [line for line in done.stdout.splitlines()
               if "a\\|b" in line]
        self.assertEqual(len(row), 1)
        cells = [c for c in row[0].strip().strip("|").split(" | ") if c != ""]
        self.assertEqual(len(cells), 5)

    def test_non_numeric_size_does_not_crash(self) -> None:
        done = self.run_script("home\t/\t390x844\tabc\t1491\t0.867\n")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("abc", done.stdout)
        self.assertIn("| `home.png` | `/` | 390x844 |", done.stdout)

    def test_missing_file_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            done = subprocess.run(
                ["bash", str(SUMMARY), str(Path(tmp) / "gone.tsv")],
                capture_output=True, text=True, check=False, timeout=60)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout, "")


class CaptureScreenshotsArgTests(unittest.TestCase):
    """capture-screenshots.sh must reject bad numbers before doing anything."""

    def run_capture(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(CAPTURE), *argv],
            capture_output=True, text=True, check=False, timeout=60)

    def test_bad_wait_ms(self) -> None:
        for value in ("-5", "abc"):
            with self.subTest(value=value):
                done = self.run_capture("--wait-ms", value)
                self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
                self.assertIn("--wait-ms", done.stderr)

    def test_bad_max_wait_ms(self) -> None:
        done = self.run_capture("--max-wait-ms", "-1")
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("--max-wait-ms", done.stderr)

    def test_bad_min_kb(self) -> None:
        done = self.run_capture("--min-kb", "-1")
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("--min-kb", done.stderr)

    def test_bad_port(self) -> None:
        for value in ("0", "70000", "abc"):
            with self.subTest(value=value):
                done = self.run_capture("--port", value)
                self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
                self.assertIn("--port", done.stderr)

    def test_bad_url_strategy(self) -> None:
        done = self.run_capture("--url-strategy", "bogus")
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("hash or path", done.stderr)

    def test_valid_args_pass_validation(self) -> None:
        # Valid numbers get past validation and fail later, on the build dir -
        # proof the validation order is up front.
        with tempfile.TemporaryDirectory() as tmp:
            done = self.run_capture(
                '--wait-ms', '1000', '--max-wait-ms', '2000', '--min-kb', '5',
                '--port', '8080', '--url-strategy', 'path',
                '--build-dir', tmp)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("index.html not found", done.stderr)


if __name__ == "__main__":
    unittest.main()

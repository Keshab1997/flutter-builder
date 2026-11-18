#!/usr/bin/env node
/**
 * Screenshot a running web app, one PNG per route and viewport.
 *
 * Why this is a script instead of `npx playwright screenshot`:
 *
 *  * the CLI takes one shot after a fixed delay and cannot tell whether the
 *    page ever painted. The first two runs of this pipeline produced a 2 KB
 *    white 390x844 PNG three times in a row - the same picture at 15 s, 30 s
 *    and 60 s - and nothing in the log said why;
 *  * this script polls until the PNG actually has content, and when it does not
 *    it prints the page's console messages, page errors, failed requests and
 *    whether the Flutter engine booted (flutter-view / flt-glass-pane) and
 *    whether WebGL is available. That is the difference between "blank" and
 *    "here is why";
 *  * one browser serves every route and viewport, so a page costs a context
 *    switch instead of a browser launch.
 *
 * Used by scripts/capture-screenshots.sh; needs the `playwright` module on
 * NODE_PATH (the shell script installs it into a temp directory).
 *
 * The pure helpers (parseArgs, pngStats, looksBlank, slug, fragment, pageUrl,
 * shotFileBase, pickBestFrame) are exported so tests can exercise them without
 * a browser; main() only runs when the file is executed directly.
 *
 * Exit codes: 0 = every requested page produced a PNG (blank ones are reported
 * in the JSON), 1 = nothing could be captured at all (or an argument was bad).
 */
'use strict';

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

function fail(message) {
  console.error(`capture-pages: ${message}`);
  process.exit(1);
}

/**
 * Pure: parses and validates the CLI flags, throwing on anything bad. The
 * caller (main) turns the throw into a logged exit, and tests can check the
 * validation in-process without a browser. Numbers are validated as they
 * arrive so a bad value costs a second, not a browser launch; Number('') is
 * 0, so an empty value is rejected explicitly instead of meaning "no wait".
 */
function parseArgs(argv) {
  const args = {
    out: 'ui-screenshots',
    url: 'http://127.0.0.1:8080',
    routes: '/',
    viewports: '390x844',
    waitMs: 12000,
    maxWaitMs: 60000,
    minBytes: 5 * 1024,
    selector: '',
    urlStrategy: 'hash',
  };
  const names = {
    '--out': 'out', '--base-url': 'url', '--routes': 'routes',
    '--viewports': 'viewports', '--wait-ms': 'waitMs',
    '--max-wait-ms': 'maxWaitMs', '--min-bytes': 'minBytes',
    '--selector': 'selector', '--url-strategy': 'urlStrategy',
  };
  for (let i = 0; i < argv.length; i += 1) {
    const key = names[argv[i]];
    if (!key) throw new Error(`unknown option: ${argv[i]}`);
    const value = argv[i + 1];
    if (value === undefined) throw new Error(`${argv[i]} needs a value`);
    if (['waitMs', 'maxWaitMs', 'minBytes'].includes(key)) {
      const num = Number(value);
      if (String(value).trim() === '' || !Number.isFinite(num) || num < 0) {
        throw new Error(`${argv[i]} must be a number >= 0 (got: ${value})`);
      }
      args[key] = num;
    } else {
      args[key] = value;
    }
    i += 1;
  }
  // Viewports are positive WxH integers; an empty list is fine (main falls
  // back to a phone), a present but broken one is not.
  for (const viewport of args.viewports.split(',').map((v) => v.trim()).filter((v) => v !== '')) {
    if (!/^([1-9][0-9]*)x([1-9][0-9]*)$/.test(viewport)) {
      throw new Error(`bad viewport: ${viewport} (want positive WxH, e.g. 390x844)`);
    }
  }
  if (args.urlStrategy !== 'hash' && args.urlStrategy !== 'path') {
    throw new Error(`bad --url-strategy: ${args.urlStrategy} (want hash or path)`);
  }
  return args;
}

/**
 * Decode a PNG screenshot and report how much is actually on it.
 *
 * A byte-size threshold cannot answer "did the app paint": a solid white
 * 390x844 screenshot is ~2.8 KB, and a legitimately plain page (one flat
 * background) is only a little bigger. What separates them is the number of
 * distinct colours, which needs the pixels. Playwright writes 8-bit
 * non-interlaced RGB or RGBA, so this handles exactly that.
 *
 * Anything that is not one of those - a truncated chunk, a short IHDR, a
 * corrupt or truncated IDAT stream, an unknown row filter - returns null
 * instead of throwing: the caller falls back to the size floor rather than
 * crashing the whole capture.
 */
function pngStats(buffer) {
  if (!Buffer.isBuffer(buffer) || buffer.length < 8
    || buffer.toString('latin1', 1, 4) !== 'PNG') return null;
  let pos = 8;
  let width = 0;
  let height = 0;
  let channels = 0;
  const idat = [];
  while (pos + 8 <= buffer.length) {
    const length = buffer.readUInt32BE(pos);
    const type = buffer.toString('latin1', pos + 4, pos + 8);
    if (pos + 12 + length > buffer.length) return null;   // truncated chunk
    const data = buffer.subarray(pos + 8, pos + 8 + length);
    if (type === 'IHDR') {
      if (data.length < 13) return null;                  // short IHDR
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      const bitDepth = data[8];
      const colorType = data[9];
      if (bitDepth !== 8 || data[12] !== 0) return null;   // only 8-bit, non-interlaced
      channels = { 0: 1, 2: 3, 4: 2, 6: 4 }[colorType] || 0;
      if (!channels) return null;
    } else if (type === 'IDAT') {
      idat.push(data);
    } else if (type === 'IEND') {
      break;
    }
    pos += 12 + length;
  }
  if (!width || !height || idat.length === 0) return null;

  let raw;
  try {
    raw = zlib.inflateSync(Buffer.concat(idat));
  } catch (error) {
    return null;                                           // corrupt IDAT stream
  }
  const stride = width * channels;
  if (raw.length < (stride + 1) * height) return null;     // truncated inflated buffer
  const pixels = Buffer.alloc(stride * height);
  for (let y = 0, src = 0; y < height; y += 1) {
    const filter = raw[src];
    src += 1;
    const rowStart = y * stride;
    const prevStart = (y - 1) * stride;
    for (let x = 0; x < stride; x += 1) {
      const value = raw[src + x];
      const left = x >= channels ? pixels[rowStart + x - channels] : 0;
      const up = y > 0 ? pixels[prevStart + x] : 0;
      const upLeft = y > 0 && x >= channels ? pixels[prevStart + x - channels] : 0;
      let out;
      switch (filter) {
        case 0: out = value; break;
        case 1: out = value + left; break;
        case 2: out = value + up; break;
        case 3: out = value + ((left + up) >> 1); break;
        case 4: {
          const p = left + up - upLeft;
          const pa = Math.abs(p - left);
          const pb = Math.abs(p - up);
          const pc = Math.abs(p - upLeft);
          out = value + ((pa <= pb && pa <= pc) ? left : (pb <= pc ? up : upLeft));
          break;
        }
        default: return null;                              // unknown filter type
      }
      pixels[rowStart + x] = out & 0xff;
    }
    src += stride;
  }

  // Sample every 16th pixel: enough to see text and icons, cheap on a 390x844.
  const counts = new Map();
  let sampled = 0;
  for (let y = 0; y < height; y += 4) {
    for (let x = 0; x < width; x += 4) {
      const offset = y * stride + x * channels;
      const key = (pixels[offset] << 16) | (pixels[offset + 1] << 8) | pixels[offset + 2];
      counts.set(key, (counts.get(key) || 0) + 1);
      sampled += 1;
    }
  }
  let top = 0;
  for (const count of counts.values()) top = Math.max(top, count);
  return {
    width,
    height,
    distinct: counts.size,
    topShare: sampled ? top / sampled : 1,
  };
}

/** Blank means literally flat: a fill, or a fill plus one other colour. */
function looksBlank(stats) {
  if (!stats) return false;                    // undecodable: do not guess
  return stats.distinct <= 2;
}

function slug(text) {
  const cleaned = String(text).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return cleaned || 'home';          // '/' slugs to nothing
}

function fragment(route) {
  const trimmed = String(route).trim();
  if (trimmed === '' || trimmed === '/' || trimmed === '#' || trimmed === '#/') return '#/';
  return trimmed.startsWith('#') ? trimmed : `#${trimmed}`;
}

/**
 * The URL that actually renders the route. Hash-routed apps (Flutter web's
 * default) take the route in the fragment - <base>/#<route> - while
 * path-routed apps (usePathUrlStrategy) serve it at <base><route>.
 */
function pageUrl(baseUrl, route, strategy = 'hash') {
  const base = String(baseUrl).replace(/\/+$/, '');
  const trimmed = String(route).trim() || '/';
  if (strategy === 'path') {
    return trimmed.startsWith('/') ? `${base}${trimmed}` : `${base}/${trimmed}`;
  }
  return `${base}/${fragment(trimmed)}`;
}

/**
 * The PNG name (without .png) for a route and viewport. slug() collides -
 * "/a/b" and "/a-b" both slug to "a-b" - so the run-shared Set keeps the
 * names unique: the second writer gets a-2, a-3, ... instead of silently
 * overwriting the first PNG.
 */
function shotFileBase(route, width, height, used = new Set()) {
  const base = `${slug(route)}-${width}x${height}`;
  let candidate = base;
  let suffix = 2;
  while (used.has(candidate)) {
    candidate = `${base}-${suffix}`;
    suffix += 1;
  }
  used.add(candidate);
  return candidate;
}

/**
 * One step of the screenshot poll: fold a freshly captured frame
 * ({ buffer, stats }) into the best frame so far. A non-blank frame wins
 * immediately and stops the poll - even when its PNG bytes are smaller than
 * an earlier blank one, because content, not size, is the signal. While
 * everything is still blank the largest buffer is the best candidate: blank
 * frames only grow as the page paints.
 */
function pickBestFrame(frame, best) {
  if (frame.stats && !looksBlank(frame.stats)) return { best: frame, done: true };
  if (!best || frame.buffer.length > best.buffer.length) return { best: frame, done: false };
  return { best, done: false };
}

async function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    fail(error.message);
  }
  let chromium;
  try {
    ({ chromium } = require('playwright'));
  } catch (error) {
    fail(`the playwright module is not on NODE_PATH (${error.message})`);
  }

  fs.mkdirSync(args.out, { recursive: true });
  const manifest = path.join(args.out, 'manifest.tsv');
  fs.writeFileSync(manifest, '');

  const routes = args.routes.split(',').map((r) => r.trim()).filter((r) => r !== '');
  const viewports = args.viewports.split(',').map((v) => v.trim()).filter((v) => v !== '');
  if (routes.length === 0) routes.push('/');
  if (viewports.length === 0) viewports.push('390x844');

  const results = [];
  const usedNames = new Set();
  let browser = null;
  try {
    // Locale and WebGL flags are not optional here, they are the fix for a
    // failure that took three CI runs to see: a headless Chromium reports no
    // usable locale, so the Flutter engine throws
    //   RangeError: Incorrect locale information provided
    // while booting and never creates a canvas - a white screenshot with no
    // visible explanation. --enable-unsafe-swiftshader is the software WebGL
    // path Chromium now requires explicitly, so a runner without a GPU still
    // paints. (Headless CI renders trusted content; that is what the flag is for.)
    browser = await chromium.launch({
      args: ['--lang=en-US', '--enable-unsafe-swiftshader'],
      env: { ...process.env, LANG: 'en_US.UTF-8', LC_ALL: 'en_US.UTF-8' },
    });

    for (const viewport of viewports) {
      const [width, height] = viewport.split('x').map(Number);
      for (const route of routes) {
        const url = pageUrl(args.url, route, args.urlStrategy);
        const file = path.join(args.out, `${shotFileBase(route, width, height, usedNames)}.png`);
        const messages = [];
        // locale makes navigator.language a real tag instead of an empty
        // string; see the launch() comment above.
        const context = await browser.newContext({
          viewport: { width, height },
          locale: 'en-US',
          extraHTTPHeaders: { 'Accept-Language': 'en-US,en;q=0.9' },
        });
        const page = await context.newPage();
        page.on('console', (m) => messages.push(`console.${m.type()}: ${m.text()}`));
        page.on('pageerror', (e) => messages.push(`pageerror: ${e.message}`));
        page.on('requestfailed', (r) => messages.push(
          `requestfailed: ${r.url()} (${(r.failure() || {}).errorText || 'unknown'})`));

        const started = Date.now();
        let best = null;
        let waited = 0;
        try {
          await page.goto(url, { waitUntil: 'load', timeout: 60000 });
          if (args.selector) {
            await page.waitForSelector(args.selector, { timeout: args.waitMs })
              .catch(() => messages.push(`selector '${args.selector}' never appeared`));
          }
          // Poll: a Flutter web app paints when it is ready, not when the page
          // says it loaded, and the only trustworthy signal is the picture.
          for (;;) {
            await page.waitForTimeout(args.waitMs);
            const shot = await page.screenshot({ type: 'png' });
            waited = Date.now() - started;
            const chosen = pickBestFrame({ buffer: shot, stats: pngStats(shot) }, best);
            best = chosen.best;
            if (chosen.done) break;         // pixels appeared
            if (waited >= args.maxWaitMs) break;
          }
          if (best) fs.writeFileSync(file, best.buffer);
        } catch (error) {
          messages.push(`navigation/screenshot failed: ${error.message}`);
        }

        const bytes = best ? best.buffer.length : 0;
        const stats = best ? best.stats : null;

        // Diagnostics: the engine's elements live in shadow DOM, so they are
        // counted with locators (page.evaluate cannot see through it).
        const info = {
          flutterView: await page.locator('flutter-view').count().catch(() => -1),
          glassPane: await page.locator('flt-glass-pane').count().catch(() => -1),
          canvases: await page.locator('canvas').count().catch(() => -1),
        };
        Object.assign(info, await page.evaluate(() => {
          const out = { title: document.title, bodyText: '' };
          try {
            out.bodyText = (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 120);
          } catch (error) { /* not fatal */ }
          try {
            const probe = document.createElement('canvas');
            const gl = probe.getContext('webgl2') || probe.getContext('webgl');
            out.webgl = !!gl;
            if (gl) {
              const debug = gl.getExtension('WEBGL_debug_renderer_info');
              out.renderer = debug ? String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)) : 'unknown';
            }
          } catch (error) { out.webgl = `error: ${error.message}`; }
          return out;
        }).catch(() => ({})));

        // The decoded pixels decide. The size floor is only a fallback for a
        // screenshot this script could not decode - a legitimate but plain page
        // measured 4.4 KB with 15 colours while a white 390x844 shot is 2.8 KB,
        // so size on its own would call the working page blank.
        const blank = stats ? looksBlank(stats) : bytes < args.minBytes;
        const record = {
          file: path.basename(file),
          route,
          viewport: `${width}x${height}`,
          bytes,
          distinctColors: stats ? stats.distinct : null,
          topColorShare: stats ? Number(stats.topShare.toFixed(3)) : null,
          waitedMs: waited,
          blank,
          info,
          messages: messages.slice(-25),
        };
        results.push(record);

        // No file, no row: a manifest line for a PNG that was never written is
        // a phantom every downstream consumer has to defend against. The
        // failure itself still lands in `results` and in the messages above.
        if (best) {
          fs.appendFileSync(manifest,
            `${path.basename(file, '.png')}\t${route}\t${width}x${height}\t${bytes}\t`
            + `${stats ? stats.distinct : -1}\t${stats ? stats.topShare.toFixed(3) : -1}\n`);
        }

        const label = best ? (blank ? 'BLANK' : 'ok') : 'MISSING';
        console.log(`  ${label.padEnd(5)} ${record.file}  ${(bytes / 1024).toFixed(1)} KB, `
          + `${stats ? stats.distinct : '?'} colours after ${(waited / 1000).toFixed(1)}s`);
        if (blank) {
          console.log(`        flutter-view=${info.flutterView} flt-glass-pane=${info.glassPane} `
            + `canvas=${info.canvases} webgl=${info.webgl} renderer=${info.renderer || 'n/a'}`);
          if (info.bodyText) console.log(`        body text: ${info.bodyText}`);
          for (const message of record.messages.slice(-12)) {
            console.log(`        ${message}`);
          }
        }
        await context.close().catch(() => {});
      }
    }
  } finally {
    // The browser belongs to the run, not to the route: a crashed page must
    // not leave a headless shell behind, and the report below must still print.
    if (browser) {
      try { await browser.close(); } catch (error) { /* already gone */ }
    }
  }

  const captured = results.filter((r) => fs.existsSync(path.join(args.out, r.file))).length;
  console.log(JSON.stringify({ captured, blank: results.filter((r) => r.blank).length,
    results }, null, 2));
  if (captured === 0) fail('no page could be captured');
  process.exit(0);
}

module.exports = {
  parseArgs,
  pngStats,
  looksBlank,
  slug,
  fragment,
  pageUrl,
  shotFileBase,
  pickBestFrame,
};

if (require.main === module) {
  main().catch((error) => fail(error.stack || String(error)));
}

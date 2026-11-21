'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const https = require('https');
const http = require('http');
const { execFileSync } = require('child_process');

const GITHUB_REPO = 'Leo-luxy/Floe';

function resolvePlatformAsset(version) {
  const plat = process.platform;
  const arch = process.arch === 'arm64' ? 'arm64' : 'x64';

  if (plat === 'darwin') {
    return {
      archiveName: `Floe-v${version}-macos-${arch}.tar.gz`,
      exeRelPath: path.join('Floe', 'floe'),
      isZip: false,
    };
  }
  if (plat === 'win32') {
    return {
      archiveName: `Floe-v${version}-windows-x64.zip`,
      exeRelPath: path.join('Floe', 'Floe.exe'),
      isZip: true,
    };
  }
  if (plat === 'linux') {
    return {
      archiveName: `Floe-v${version}-linux-x64.tar.gz`,
      exeRelPath: path.join('Floe', 'floe'),
      isZip: false,
    };
  }
  throw new Error(`Unsupported OS platform: ${plat}-${arch}`);
}

function getCacheRoot(version) {
  const home = os.homedir();
  if (process.platform === 'darwin') {
    return path.join(home, 'Library', 'Caches', 'Floe', `v${version}`);
  }
  if (process.platform === 'win32') {
    const localAppData = process.env.LOCALAPPDATA || path.join(home, 'AppData', 'Local');
    return path.join(localAppData, 'Floe', 'Cache', `v${version}`);
  }
  const xdgCache = process.env.XDG_CACHE_HOME || path.join(home, '.cache');
  return path.join(xdgCache, 'floe', `v${version}`);
}

function downloadFile(url, destPath, redirectsLeft = 6) {
  return new Promise((resolve, reject) => {
    if (redirectsLeft <= 0) {
      return reject(new Error('Too many HTTP redirects'));
    }
    const client = url.startsWith('https:') ? https : http;
    const req = client.get(url, { headers: { 'User-Agent': 'Floe-NPM-Installer/2.0' } }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        res.resume();
        const nextUrl = new URL(res.headers.location, url).toString();
        return resolve(downloadFile(nextUrl, destPath, redirectsLeft - 1));
      }
      if (res.statusCode !== 200) {
        res.resume();
        return reject(new Error(`HTTP ${res.statusCode} when fetching ${url}`));
      }
      const total = parseInt(res.headers['content-length'] || '0', 10);
      let downloaded = 0;
      let lastPct = -1;
      const out = fs.createWriteStream(destPath);
      res.on('data', (chunk) => {
        downloaded += chunk.length;
        if (total > 0) {
          const pct = Math.floor((downloaded / total) * 100);
          if (pct >= lastPct + 10) {
            lastPct = pct;
            process.stdout.write(`\r[Floe] Downloading runtime package... ${pct}%`);
          }
        }
      });
      res.pipe(out);
      out.on('finish', () => {
        out.close(() => {
          if (total > 0) process.stdout.write('\n');
          resolve();
        });
      });
      out.on('error', reject);
    });
    req.on('error', reject);
  });
}

async function ensureBinaryInstalled(version) {
  const spec = resolvePlatformAsset(version);
  const cacheDir = getCacheRoot(version);
  const exePath = path.join(cacheDir, spec.exeRelPath);

  if (fs.existsSync(exePath)) {
    return exePath;
  }

  fs.mkdirSync(cacheDir, { recursive: true });
  const rawUrl = `https://github.com/${GITHUB_REPO}/releases/download/v${version}/${spec.archiveName}`;
  const mirrorPrefix = (process.env.FLOE_GITHUB_MIRROR || '').trim();
  const downloadUrl = mirrorPrefix ? `${mirrorPrefix.replace(/\/?$/, '/')}${rawUrl}` : rawUrl;

  const tmpArchive = path.join(cacheDir, spec.archiveName);
  console.log(`[Floe] First-run setup: fetching ${spec.archiveName}...`);
  await downloadFile(downloadUrl, tmpArchive);

  console.log('[Floe] Extracting runtime bundle...');
  if (spec.isZip) {
    // Windows 10/11 内置 tar 或 PowerShell Expand-Archive
    execFileSync('powershell', [
      '-NoProfile',
      '-Command',
      `Expand-Archive -LiteralPath '${tmpArchive}' -DestinationPath '${cacheDir}' -Force`,
    ], { stdio: 'inherit' });
  } else {
    execFileSync('tar', ['-xzf', tmpArchive, '-C', cacheDir], { stdio: 'inherit' });
    fs.chmodSync(exePath, 0o755);
  }

  try {
    fs.unlinkSync(tmpArchive);
  } catch (_) {}

  if (!fs.existsSync(exePath)) {
    throw new Error(`Extracted archive did not contain expected binary: ${exePath}`);
  }
  return exePath;
}

module.exports = { ensureBinaryInstalled, resolvePlatformAsset };

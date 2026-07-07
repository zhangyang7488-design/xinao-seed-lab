const { app, BrowserWindow, ipcMain, screen } = require('electron');
const fs = require('fs');
const path = require('path');

const isSmoke = process.argv.includes('--smoke');
const DEFAULT_WIDTH = 1110;
const DEFAULT_HEIGHT = 1259;
const MIN_WIDTH = 920;
const MIN_HEIGHT = 620;

app.setName('XINAOSurface');

// Material contract: this shell is judged by depth, pressure, and button feel.
// Do not turn it into owner.html, an Edge app, a chat wrapper, or a flat long-page console.

function boundsPath() {
  return path.join(app.getPath('userData'), 'window-bounds.json');
}

function isBoundsVisible(bounds) {
  const displays = screen.getAllDisplays();
  return displays.some((display) => {
    const area = display.workArea;
    const right = bounds.x + bounds.width;
    const bottom = bounds.y + bounds.height;
    return bounds.x < area.x + area.width
      && right > area.x
      && bounds.y < area.y + area.height
      && bottom > area.y;
  });
}

function readWindowBounds() {
  try {
    const raw = fs.readFileSync(boundsPath(), 'utf8');
    const parsed = JSON.parse(raw);
    const bounds = {
      x: Number(parsed.x),
      y: Number(parsed.y),
      width: Math.max(MIN_WIDTH, Number(parsed.width)),
      height: Math.max(MIN_HEIGHT, Number(parsed.height))
    };
    if (Number.isFinite(bounds.x)
      && Number.isFinite(bounds.y)
      && Number.isFinite(bounds.width)
      && Number.isFinite(bounds.height)
      && isBoundsVisible(bounds)) {
      return bounds;
    }
  } catch {
    // First launch or unreadable state: fall back to the material sample default.
  }
  return { width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT };
}

function saveWindowBounds(win) {
  if (win.isDestroyed() || win.isMinimized() || win.isFullScreen()) return;
  const bounds = win.getBounds();
  fs.mkdirSync(path.dirname(boundsPath()), { recursive: true });
  fs.writeFileSync(boundsPath(), JSON.stringify({
    schema_version: 'xinao.surface.window_bounds.v1',
    saved_at: new Date().toISOString(),
    x: bounds.x,
    y: bounds.y,
    width: bounds.width,
    height: bounds.height,
    maximized: win.isMaximized()
  }, null, 2));
}

function createWindow() {
  const savedBounds = readWindowBounds();
  const win = new BrowserWindow({
    ...savedBounds,
    minWidth: MIN_WIDTH,
    minHeight: MIN_HEIGHT,
    backgroundColor: '#eef1f3',
    frame: false,
    resizable: true,
    show: false,
    title: 'XINAOSurface',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  win.once('ready-to-show', () => {
    win.show();
    if (isSmoke) {
      setTimeout(async () => {
        const image = await win.webContents.capturePage();
        const out = path.join(app.getPath('temp'), 'xinao-surface-smoke.png');
        require('fs').writeFileSync(out, image.toPNG());
        console.log(JSON.stringify({ screenshot: out, size: image.getSize() }));
        app.quit();
      }, 650);
    }
  });

  win.on('close', () => saveWindowBounds(win));

  win.loadFile(path.join(__dirname, 'renderer.html'));
  return win;
}

app.whenReady().then(() => {
  const win = createWindow();

  ipcMain.handle('window:minimize', () => win.minimize());
  ipcMain.handle('window:toggle-maximize', () => {
    if (win.isMaximized()) {
      win.unmaximize();
    } else {
      win.maximize();
    }
  });
  ipcMain.handle('window:close', () => win.close());
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

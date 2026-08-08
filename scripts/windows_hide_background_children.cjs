"use strict";

// This preload belongs only to non-interactive regression runners.  It keeps
// their Windows descendants attached to the existing invisible/background
// execution surface instead of flashing a console for every fresh process.
// Interactive Codex/TUI launchers do not load this file.
if (process.platform === "win32") {
  const childProcess = require("node:child_process");
  const { syncBuiltinESMExports } = require("node:module");

  const hiddenOptions = (value) => ({
    ...(value && typeof value === "object" ? value : {}),
    windowsHide: true,
  });
  const mark = (fn) => {
    Object.defineProperty(fn, "xinaoBackgroundWindowsHidden", {
      value: true,
      enumerable: false,
    });
    return fn;
  };

  if (!childProcess.spawn.xinaoBackgroundWindowsHidden) {
    const original = childProcess.spawn;
    childProcess.spawn = mark(function spawn(command, args, options) {
      if (Array.isArray(args)) {
        return original.call(this, command, args, hiddenOptions(options));
      }
      return original.call(this, command, hiddenOptions(args));
    });
  }

  if (!childProcess.spawnSync.xinaoBackgroundWindowsHidden) {
    const original = childProcess.spawnSync;
    childProcess.spawnSync = mark(function spawnSync(command, args, options) {
      if (Array.isArray(args)) {
        return original.call(this, command, args, hiddenOptions(options));
      }
      return original.call(this, command, hiddenOptions(args));
    });
  }

  if (!childProcess.execFile.xinaoBackgroundWindowsHidden) {
    const original = childProcess.execFile;
    childProcess.execFile = mark(function execFile(file, args, options, callback) {
      if (Array.isArray(args)) {
        if (typeof options === "function") {
          return original.call(this, file, args, hiddenOptions(), options);
        }
        return original.call(this, file, args, hiddenOptions(options), callback);
      }
      if (typeof args === "function") {
        return original.call(this, file, hiddenOptions(), args);
      }
      return original.call(this, file, hiddenOptions(args), options);
    });
  }

  if (!childProcess.execFileSync.xinaoBackgroundWindowsHidden) {
    const original = childProcess.execFileSync;
    childProcess.execFileSync = mark(function execFileSync(file, args, options) {
      if (Array.isArray(args)) {
        return original.call(this, file, args, hiddenOptions(options));
      }
      return original.call(this, file, hiddenOptions(args));
    });
  }

  if (!childProcess.exec.xinaoBackgroundWindowsHidden) {
    const original = childProcess.exec;
    childProcess.exec = mark(function exec(command, options, callback) {
      if (typeof options === "function") {
        return original.call(this, command, hiddenOptions(), options);
      }
      return original.call(this, command, hiddenOptions(options), callback);
    });
  }

  if (!childProcess.execSync.xinaoBackgroundWindowsHidden) {
    const original = childProcess.execSync;
    childProcess.execSync = mark(function execSync(command, options) {
      return original.call(this, command, hiddenOptions(options));
    });
  }

  if (!childProcess.fork.xinaoBackgroundWindowsHidden) {
    const original = childProcess.fork;
    childProcess.fork = mark(function fork(modulePath, args, options) {
      if (Array.isArray(args)) {
        return original.call(this, modulePath, args, hiddenOptions(options));
      }
      return original.call(this, modulePath, [], hiddenOptions(args));
    });
  }

  // Update ESM named exports after patching the CommonJS builtin object.
  syncBuiltinESMExports();
}

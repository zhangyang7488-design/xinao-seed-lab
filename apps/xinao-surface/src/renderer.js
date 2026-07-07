const actions = {
  minimize: () => window.xinaoWindow.minimize(),
  maximize: () => window.xinaoWindow.toggleMaximize(),
  close: () => window.xinaoWindow.close()
};

document.querySelectorAll('[data-window]').forEach((button) => {
  button.addEventListener('click', () => {
    actions[button.dataset.window]();
  });
});

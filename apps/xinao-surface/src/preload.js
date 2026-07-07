const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('xinaoWindow', {
  minimize: () => ipcRenderer.invoke('window:minimize'),
  toggleMaximize: () => ipcRenderer.invoke('window:toggle-maximize'),
  close: () => ipcRenderer.invoke('window:close')
});

contextBridge.exposeInMainWorld('xinaoStatus', {
  schemaVersion: 'xinao.surface.operator_view.v1',
  read: () => ipcRenderer.invoke('status:read')
});

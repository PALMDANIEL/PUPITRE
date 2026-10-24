// Pont minimal entre la fenêtre d'activation et l'application (rien d'autre n'est exposé à la page).
import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('pupitre', {
  status: () => ipcRenderer.invoke('licence:status'),
  copyMachine: () => ipcRenderer.invoke('licence:copy'),
  openFile: () => ipcRenderer.invoke('licence:open-file'),
  install: (text: string) => ipcRenderer.invoke('licence:install', text),
  credits: () => ipcRenderer.invoke('credits'),
});

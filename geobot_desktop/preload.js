const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("geobotApi", {
  getHealth: () => ipcRenderer.invoke("geobot:health"),
  getPopulationShowcase: () => ipcRenderer.invoke("geobot:get-population-showcase"),
  createProject: (payload) => ipcRenderer.invoke("geobot:create-project", payload),
  getProject: (projectId) => ipcRenderer.invoke("geobot:get-project", projectId),
  listTemplates: () => ipcRenderer.invoke("geobot:list-templates"),
  submitTemplate: (templateId, payload) => ipcRenderer.invoke("geobot:submit-template", templateId, payload),
  submitChat: (payload) => ipcRenderer.invoke("geobot:submit-chat", payload),
  getJob: (jobId) => ipcRenderer.invoke("geobot:get-job", jobId),
  getArtifact: (artifactId) => ipcRenderer.invoke("geobot:get-artifact", artifactId),
  listOutputs: (projectId) => ipcRenderer.invoke("geobot:list-outputs", projectId),
  focusQgis: () => ipcRenderer.invoke("geobot:focus-qgis"),
  getRuntimeUrl: () => ipcRenderer.invoke("geobot:get-runtime-url"),
  openPath: (targetPath) => ipcRenderer.invoke("geobot:open-path", targetPath),
  showInFolder: (targetPath) => ipcRenderer.invoke("geobot:show-in-folder", targetPath),
});

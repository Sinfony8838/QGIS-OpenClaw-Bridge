const { app } = require("electron");
const path = require("path");
const { runOpenClawAutomation, buildError } = require(path.join(__dirname, "..", "geobot_desktop", "openclaw_bridge_runner"));

function getArg(flag) {
  const index = process.argv.indexOf(flag);
  if (index >= 0 && index + 1 < process.argv.length) {
    return process.argv[index + 1];
  }
  return "";
}

function flushResultAndExit(result) {
  const payload = `${JSON.stringify(result)}\n`;
  try {
    process.stdout.write(payload);
  } catch (error) {
    console.error(JSON.stringify(buildError(error.message || String(error))));
  }
  setTimeout(() => {
    app.exit(result.status === "success" ? 0 : 1);
  }, 100);
}

app.on("window-all-closed", (event) => {
  event.preventDefault();
});

process.on("uncaughtException", (error) => {
  flushResultAndExit(buildError(error.message || String(error)));
});

process.on("unhandledRejection", (reason) => {
  const message = reason && reason.message ? reason.message : String(reason);
  flushResultAndExit(buildError(message));
});

app.whenReady().then(async () => {
  const requestPath = getArg("--request");
  if (!requestPath) {
    flushResultAndExit(buildError("Missing --request argument"));
    return;
  }
  let request;
  try {
    request = require("fs").readFileSync(requestPath, "utf8");
    request = JSON.parse(request);
  } catch (error) {
    flushResultAndExit(buildError(error.message || String(error)));
    return;
  }
  const result = await runOpenClawAutomation(request);
  flushResultAndExit(result);
});

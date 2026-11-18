const copyButton = document.getElementById("copy-pair-code");
const pairingCode = document.getElementById("pair-code");
const copyResult = document.getElementById("copy-result");

copyButton.hidden = false;
copyButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(pairingCode.value);
    copyResult.textContent = "Pairing token copied.";
  } catch {
    pairingCode.focus();
    pairingCode.select();
    copyResult.textContent = "Copy the selected pairing token using your keyboard.";
  }
});

const pairingStatus = document.getElementById("pairing-status");
const statusUrl = "/devices/pair/status/" + encodeURIComponent(pairingStatus.dataset.deviceId);
const stopCheckingAt = Date.now() + 5 * 60 * 1000;
const waitingMessage = pairingStatus.textContent;

async function checkPairingStatus() {
  if (Date.now() >= stopCheckingAt) {
    pairingStatus.textContent = "Automatic checking paused. Open Paired Computers to check your connection.";
    return;
  }

  if (!document.hidden) {
    try {
      const response = await fetch(statusUrl, { cache: "no-store", signal: AbortSignal.timeout(5000) });
      if (response.status === 401 || response.status === 404) {
        pairingStatus.textContent = "This pairing is unavailable. Open Paired Computers to continue.";
        return;
      }
      if (!response.ok) throw new Error("Status check unavailable");

      const { connected } = await response.json();
      if (connected) {
        pairingStatus.textContent = "Connected. Your computer is ready to use in ChatGPT.";
        pairingCode.value = "";
        copyButton.disabled = true;
        copyResult.textContent = "";
        return;
      }
      if (pairingStatus.textContent !== waitingMessage) pairingStatus.textContent = waitingMessage;
    } catch {
      const retryMessage = "Connection status temporarily unavailable. Checking again…";
      if (pairingStatus.textContent !== retryMessage) pairingStatus.textContent = retryMessage;
    }
  }
  setTimeout(checkPairingStatus, 4000);
}

checkPairingStatus();

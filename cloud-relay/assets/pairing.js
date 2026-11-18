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

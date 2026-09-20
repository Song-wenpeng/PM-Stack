const status = document.getElementById("status");
async function run(type) {
  try {
    const token = document.getElementById("token").value.trim();
    const result = await chrome.runtime.sendMessage({type, token});
    status.textContent = result.message;
  } catch (error) { status.textContent = String(error); }
}
document.getElementById("connect").onclick = () => run("CONNECT");
document.getElementById("check").onclick = () => run("CHECK");
document.getElementById("disconnect").onclick = () => run("DISCONNECT");
chrome.storage.local.get(["lastMessage"]).then(s => {status.textContent = s.lastMessage || "在 PM Stack 启动连接并复制连接码";});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.lastMessage) status.textContent = changes.lastMessage.newValue || "";
});

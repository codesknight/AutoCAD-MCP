const conversationId = crypto.randomUUID();

const providerSelect = document.getElementById("provider");
const baseUrlRow = document.getElementById("base_url_row");
const apiKeyInput = document.getElementById("api_key");
const baseUrlInput = document.getElementById("base_url");
const log = document.getElementById("log");
const messageInput = document.getElementById("message");
const sendButton = document.getElementById("send");

providerSelect.addEventListener("change", () => {
  baseUrlRow.style.display = providerSelect.value === "openai_compatible" ? "flex" : "none";
});

function appendMessage(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = (role === "user" ? "你：" : "助手：") + text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

async function sendMessage() {
  const message = messageInput.value.trim();
  if (!message) return;
  const apiKey = apiKeyInput.value.trim();
  if (!apiKey) {
    alert("请先填写 API Key");
    return;
  }

  appendMessage("user", message);
  messageInput.value = "";
  sendButton.disabled = true;

  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversation_id: conversationId,
        provider: providerSelect.value,
        api_key: apiKey,
        base_url: providerSelect.value === "openai_compatible" ? baseUrlInput.value.trim() : null,
        message,
      }),
    });
    if (!resp.ok) {
      const errText = await resp.text();
      appendMessage("assistant", `请求失败：${resp.status} ${errText}`);
      return;
    }
    const data = await resp.json();
    appendMessage("assistant", data.reply);
  } catch (err) {
    appendMessage("assistant", `网络错误：${err}`);
  } finally {
    sendButton.disabled = false;
  }
}

sendButton.addEventListener("click", sendMessage);
messageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});

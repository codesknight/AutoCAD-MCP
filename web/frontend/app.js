const conversationId = crypto.randomUUID();

const providerSelect = document.getElementById("provider");
const baseUrlRow = document.getElementById("base_url_row");
const baseUrlHintRow = document.getElementById("base_url_hint_row");
const apiKeyInput = document.getElementById("api_key");
const baseUrlInput = document.getElementById("base_url");
const modelInput = document.getElementById("model");
const log = document.getElementById("log");
const messageInput = document.getElementById("message");
const sendButton = document.getElementById("send");
const imageInput = document.getElementById("image");
const imagePreview = document.getElementById("image_preview");

let pendingImage = null; // { base64, mediaType } | null

// Providers with no sane default base_url/model (arbitrary compatible
// endpoint, or an Ark inference endpoint ID) -- must match agent_loop.py's
// MODEL_REQUIRED_PROVIDERS.
const BASE_URL_AND_MODEL_REQUIRED_PROVIDERS = ["openai_compatible", "doubao"];

providerSelect.addEventListener("change", () => {
  const showBaseUrl = BASE_URL_AND_MODEL_REQUIRED_PROVIDERS.includes(providerSelect.value);
  baseUrlRow.style.display = showBaseUrl ? "flex" : "none";
  baseUrlHintRow.style.display = showBaseUrl ? "flex" : "none";
});

imageInput.addEventListener("change", () => {
  const file = imageInput.files[0];
  if (!file) {
    pendingImage = null;
    imagePreview.style.display = "none";
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    const dataUrl = reader.result; // "data:image/png;base64,AAAA..."
    const [, mediaType, base64] = dataUrl.match(/^data:(.+);base64,(.*)$/);
    pendingImage = { base64, mediaType };
    imagePreview.src = dataUrl;
    imagePreview.style.display = "block";
  };
  reader.readAsDataURL(file);
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
  if (!message && !pendingImage) return;
  const apiKey = apiKeyInput.value.trim();
  // API Key is optional -- some locally-deployed OpenAI-compatible servers
  // don't check auth at all. Cloud providers will simply fail with their
  // own auth error if left blank.
  const model = modelInput.value.trim();
  if (BASE_URL_AND_MODEL_REQUIRED_PROVIDERS.includes(providerSelect.value) && !model) {
    alert("使用 OpenAI 兼容 / 豆包模式时必须填写模型名称");
    return;
  }

  const effectiveMessage = message || "请根据这张图片，用现有工具在 AutoCAD 里画出对应的图形。";
  appendMessage("user", effectiveMessage + (pendingImage ? "（附带图片）" : ""));
  messageInput.value = "";
  const imageToSend = pendingImage;
  clearPendingImage();
  sendButton.disabled = true;

  // Some tools (e.g. VQA over a locally-hosted model) can legitimately take
  // 1-2+ minutes -- without visible progress this looks identical to the
  // page being stuck, so show an elapsed-time indicator while waiting.
  const thinkingDiv = document.createElement("div");
  thinkingDiv.className = "msg assistant";
  const startTime = Date.now();
  const updateThinking = () => {
    const secs = Math.round((Date.now() - startTime) / 1000);
    thinkingDiv.textContent = `助手：思考中...（已等待 ${secs} 秒，复杂任务可能需要 1-2 分钟）`;
  };
  updateThinking();
  log.appendChild(thinkingDiv);
  log.scrollTop = log.scrollHeight;
  const thinkingTimer = setInterval(updateThinking, 1000);

  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversation_id: conversationId,
        provider: providerSelect.value,
        api_key: apiKey,
        base_url: BASE_URL_AND_MODEL_REQUIRED_PROVIDERS.includes(providerSelect.value)
          ? baseUrlInput.value.trim() || null
          : null,
        model: model || null,
        message: effectiveMessage,
        image_base64: imageToSend ? imageToSend.base64 : null,
        image_media_type: imageToSend ? imageToSend.mediaType : null,
      }),
    });
    if (!resp.ok) {
      const errText = await resp.text();
      thinkingDiv.remove();
      appendMessage("assistant", `请求失败：${resp.status} ${errText}`);
      return;
    }
    const data = await resp.json();
    thinkingDiv.remove();
    appendMessage("assistant", data.reply);
  } catch (err) {
    thinkingDiv.remove();
    appendMessage("assistant", `网络错误：${err}`);
  } finally {
    clearInterval(thinkingTimer);
    sendButton.disabled = false;
  }
}

function clearPendingImage() {
  pendingImage = null;
  imageInput.value = "";
  imagePreview.style.display = "none";
}

sendButton.addEventListener("click", sendMessage);
messageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});

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

  // Streaming reply: text accumulates into replyDiv as it arrives; tool
  // calls get their own status line so a slow tool (e.g. VQA, 1-2+ minutes)
  // shows *what* it's doing instead of a generic "thinking..." spinner.
  const replyDiv = document.createElement("div");
  replyDiv.className = "msg assistant";
  replyDiv.textContent = "助手：";
  log.appendChild(replyDiv);
  log.scrollTop = log.scrollHeight;
  let replyText = "";

  function appendStatusLine(text) {
    const statusDiv = document.createElement("div");
    statusDiv.className = "msg assistant status";
    statusDiv.textContent = text;
    log.appendChild(statusDiv);
    log.scrollTop = log.scrollHeight;
  }

  try {
    const resp = await fetch("/api/chat/stream", {
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
    if (!resp.ok || !resp.body) {
      const errText = await resp.text();
      replyDiv.textContent = `助手：请求失败：${resp.status} ${errText}`;
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop(); // last part may be incomplete, keep it for next read
      for (const part of parts) {
        const line = part.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        const event = JSON.parse(line.slice("data: ".length));
        if (event.type === "text_delta") {
          replyText += event.text;
          replyDiv.textContent = "助手：" + replyText;
          log.scrollTop = log.scrollHeight;
        } else if (event.type === "tool_call") {
          appendStatusLine(`🔧 调用工具 ${event.name}(${JSON.stringify(event.input)})`);
        } else if (event.type === "tool_result") {
          appendStatusLine(`✓ ${event.name} 完成`);
        } else if (event.type === "error") {
          appendStatusLine(`出错了：${event.message}`);
        }
      }
    }
  } catch (err) {
    appendStatusLine(`网络错误：${err}`);
  } finally {
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

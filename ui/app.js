(() => {
  const params = new URLSearchParams(location.search);
  const token = params.get("token") || "";
  const messagesEl = document.getElementById("messages");
  const inputEl = document.getElementById("input");
  const formEl = document.getElementById("composer");
  const sendBtn = document.getElementById("send");
  const resetBtn = document.getElementById("reset-btn");
  const statusDot = document.getElementById("status-dot");
  const modelName = document.getElementById("model-name");
  const confirmDlg = document.getElementById("confirm");
  const confirmDesc = document.getElementById("confirm-desc");
  const confirmArgs = document.getElementById("confirm-args");

  let ws = null;
  let reconnectDelay = 1000;
  let assistantEl = null;
  let pendingConfirm = null;

  function setStatus(state) {
    statusDot.classList.remove("connected", "connecting");
    if (state === "connected") statusDot.classList.add("connected");
    else if (state === "connecting") statusDot.classList.add("connecting");
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function addMessage(role, text) {
    const el = document.createElement("div");
    el.className = "msg " + role;
    el.textContent = text || "";
    messagesEl.appendChild(el);
    scrollToBottom();
    return el;
  }

  function ensureAssistant() {
    if (!assistantEl) {
      assistantEl = addMessage("assistant", "");
    }
    return assistantEl;
  }

  function toolCard(id, name, args) {
    const card = document.createElement("details");
    card.className = "tool-card";
    card.open = true;
    card.dataset.id = id;
    const summary = document.createElement("summary");
    summary.textContent = "🔧 " + name;
    card.appendChild(summary);
    const body = document.createElement("div");
    body.className = "tool-body";
    const argsPre = document.createElement("pre");
    argsPre.textContent = JSON.stringify(args || {}, null, 2);
    body.appendChild(argsPre);
    const result = document.createElement("div");
    result.className = "tool-result";
    result.textContent = "… in esecuzione";
    body.appendChild(result);
    card.appendChild(body);
    messagesEl.appendChild(card);
    scrollToBottom();
    return card;
  }

  function setToolResult(id, ok, result) {
    const card = [...messagesEl.querySelectorAll(".tool-card")].find(c => c.dataset.id === id);
    if (!card) return;
    const resultEl = card.querySelector(".tool-result");
    if (resultEl) {
      resultEl.textContent = (ok ? "✓ " : "✗ ") + (result || "");
      resultEl.classList.add(ok ? "ok" : "fail");
    }
    let parsed = null;
    try { parsed = JSON.parse(result); } catch (e) { parsed = null; }
    if (parsed && parsed.image) {
      const img = document.createElement("img");
      img.src = "/shots/" + encodeURIComponent(parsed.image) + "?token=" + encodeURIComponent(token);
      img.alt = "screenshot";
      img.style.maxWidth = "100%";
      img.style.borderRadius = "6px";
      img.style.marginTop = "6px";
      img.style.cursor = "pointer";
      img.addEventListener("click", () => window.open(img.src, "_blank"));
      const body = card.querySelector(".tool-body");
      if (body) body.appendChild(img);
    }
  }

  function showConfirm(id, description, args) {
    pendingConfirm = id;
    confirmDesc.textContent = description || "Confermare l'azione?";
    confirmArgs.textContent = JSON.stringify(args || {}, null, 2);
    confirmDlg.showModal();
  }

  confirmDlg.addEventListener("close", () => {
    if (pendingConfirm === null) return;
    const allow = confirmDlg.returnValue === "allow";
    send({ type: "confirm", id: pendingConfirm, allow });
    pendingConfirm = null;
  });

  function send(obj) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify(obj));
  }

  function connect() {
    setStatus("connecting");
    const url = `ws://${location.host}/ws?token=${encodeURIComponent(token)}`;
    ws = new WebSocket(url);

    ws.onopen = () => {
      setStatus("connected");
      reconnectDelay = 1000;
      sendBtn.disabled = false;
      assistantEl = null;
      addMessage("system", "Connesso.");
    };

    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      switch (msg.type) {
        case "token":
          ensureAssistant().textContent += msg.text;
          scrollToBottom();
          break;
        case "tool_call":
          toolCard(msg.id, msg.name, msg.args);
          break;
        case "tool_result":
          setToolResult(msg.id, msg.ok, msg.result);
          break;
        case "confirm_request":
          showConfirm(msg.id, msg.description, msg.args);
          break;
        case "error":
          addMessage("error", msg.message);
          break;
        case "system":
          addMessage("system", msg.text || "");
          break;
        case "done":
          assistantEl = null;
          sendBtn.disabled = false;
          break;
      }
    };

    ws.onclose = () => {
      setStatus("");
      addMessage("system", "Connessione persa. Riconnessione…");
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 5000);
    };

    ws.onerror = () => { /* gestito da onclose */ };
  }

  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      messagesEl.innerHTML = "";
      assistantEl = null;
      send({ type: "reset" });
    });
  }

  formEl.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = inputEl.value.trim();
    if (!text) return;
    addMessage("user", text);
    assistantEl = null;
    sendBtn.disabled = true;
    send({ type: "user", text });
    inputEl.value = "";
    inputEl.style.height = "auto";
  });

  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      formEl.requestSubmit();
    }
  });

  inputEl.addEventListener("input", () => {
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 140) + "px";
  });

  if (!token) {
    addMessage("error", "Token mancante nell'URL. Avvia Ayra con `python run.py`.");
    return;
  }

  connect();
})();

(() => {
  const state = {
    appVersion: "1.4.1",
    repoUrl: "https://github.com/tjcisyourdady-gif/YuiDesk",
    settings: {},
    providers: [],
    personas: [],
    skins: [],
    conversations: [],
    cliSessions: [],
    kimiCliStatus: { installed: false, message: "" },
    activeConvId: null,
    viewRunKey: null,
    activeMode: "work", // work | chat
    sidebarOpen: true,
    sidebarQuery: "",
    modeConvIds: { work: null, chat: null },
    historyFilterMode: "work", // work | chat
    messages: [],
    pendingAttachments: [],
    editingProviderId: null,
    runs: {}, // convId -> { convId, mode, startedAt, statusLabel, steps, assistantMsg, stopping, attached }
    elapsedTimer: null,
    updateInfo: null,
    updatePollTimer: null,
    settingsOnlyWindow: false,
    lastWidthSent: 496,
    lastHeightSent: 330,
  };

  const $ = (id) => document.getElementById(id);

  function showToast(msg, ms = 2000) {
    const el = $("toast");
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(() => el.classList.add("hidden"), ms);
  }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderMarkdown(raw) {
    if (!raw) return "";
    const codeBlocks = [];
    codeBlocks._raw = [];
    let text = String(raw).replace(/```([\w-]*)\n([\s\S]*?)```/g, (_, lang, code) => {
      const idx = codeBlocks.length;
      const clean = code.replace(/\n$/, "");
      codeBlocks._raw[idx] = clean;
      codeBlocks.push(
        `<div class="code-block-wrap"><div class="code-block-head"><span>${escapeHtml(lang || "code")}</span><button class="code-copy-btn" data-copy-idx="${idx}">复制</button></div><pre><code>${escapeHtml(clean)}</code></pre></div>`
      );
      return `\u0000CODEBLOCK_${idx}\u0000`;
    });

    const lines = text.split("\n");
    const out = [];
    let inUl = false;
    let inOl = false;
    let inTable = false;

    const closeAll = () => {
      if (inUl) { out.push("</ul>"); inUl = false; }
      if (inOl) { out.push("</ol>"); inOl = false; }
      if (inTable) { out.push("</tbody></table>"); inTable = false; }
    };

    const inlineFmt = (s) => {
      let h = escapeHtml(s);
      h = h.replace(/`([^`]+)`/g, "<code>$1</code>");
      h = h.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      h = h.replace(/\*([^*]+)\*/g, "<em>$1</em>");
      h = h.replace(/\[([^\]]+)\]\((https?:\/\/[^\s"'<>)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      return h;
    };

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const trimmed = line.trim();
      if (/^\u0000CODEBLOCK_\d+\u0000$/.test(trimmed)) { closeAll(); out.push(trimmed); continue; }
      if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
        const nextLine = (lines[i + 1] || "").trim();
        if (!inTable && /^\|[\s:|-]+\|$/.test(nextLine)) {
          closeAll();
          const headers = trimmed.slice(1, -1).split("|").map((c) => `<th>${inlineFmt(c.trim())}</th>`).join("");
          out.push(`<table><thead><tr>${headers}</tr></thead><tbody>`);
          inTable = true;
          i++;
          continue;
        }
        if (inTable) {
          const cols = trimmed.slice(1, -1).split("|").map((c) => `<td>${inlineFmt(c.trim())}</td>`).join("");
          out.push(`<tr>${cols}</tr>`);
          continue;
        }
      } else if (inTable) {
        out.push("</tbody></table>");
        inTable = false;
      }
      if (!trimmed) { closeAll(); continue; }
      if (/^#{1,3}\s+/.test(trimmed)) {
        closeAll();
        const lv = trimmed.match(/^(#{1,3})/)[1].length;
        out.push(`<h${lv}>${inlineFmt(trimmed.replace(/^#{1,3}\s+/, ""))}</h${lv}>`);
        continue;
      }
      if (trimmed.startsWith("> ")) { closeAll(); out.push(`<blockquote>${inlineFmt(trimmed.slice(2))}</blockquote>`); continue; }
      if (/^[-*+]\s+/.test(trimmed)) {
        if (inOl) { out.push("</ol>"); inOl = false; }
        if (!inUl) { out.push("<ul>"); inUl = true; }
        out.push(`<li>${inlineFmt(trimmed.replace(/^[-*+]\s+/, ""))}</li>`);
        continue;
      }
      if (/^\d+\.\s+/.test(trimmed)) {
        if (inUl) { out.push("</ul>"); inUl = false; }
        if (!inOl) { out.push("<ol>"); inOl = true; }
        out.push(`<li>${inlineFmt(trimmed.replace(/^\d+\.\s+/, ""))}</li>`);
        continue;
      }
      closeAll();
      out.push(`<p>${inlineFmt(line)}</p>`);
    }
    closeAll();
    window.__lastCodeBlocks = codeBlocks._raw;
    return out.join("\n").replace(/\u0000CODEBLOCK_(\d+)\u0000/g, (_, idx) => codeBlocks[Number(idx)] || "");
  }

  async function api(path, options = {}) {
    const res = await fetch(path, options);
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try { const j = await res.json(); msg = j.detail || j.message || msg; } catch (_) {}
      throw new Error(msg);
    }
    return res.json();
  }

  function applyDialogFontSize(sizePx) {
    const num = Number(sizePx);
    const clean = Number.isFinite(num) ? Math.max(10, Math.min(15, num)) : 11.5;
    document.documentElement.style.setProperty("--dialog-font", `${clean}px`);
  }

  function syncDialogHeight() {
    if (!$("settingsModal").classList.contains("hidden")) return;
    const hasMessages = state.messages.length > 0;
    const hasAtts = state.pendingAttachments.length > 0;
    const isWork = state.activeMode !== "chat";
    const prefW = Math.max(360, Math.min(760, Number(state.settings.dialog_width) || 496));
    const prefMaxH = Math.max(260, Math.min(680, Number(state.settings.dialog_max_height) || 400));
    const targetW = state.sidebarOpen ? prefW : Math.max(320, prefW - 136);
    let targetH;
    if (state.sidebarOpen) {
      const minH = Math.min(prefMaxH, Math.max(260, Math.round(prefMaxH * 0.82)));
      const contentH = hasMessages ? ($("messagesContainer").scrollHeight || 130) : 130;
      targetH = Math.min(prefMaxH, Math.max(minH, contentH + (isWork ? 186 : 158) + (hasAtts ? 26 : 0)));
    } else {
      const baseEmpty = (isWork ? 156 : 132) + (hasAtts ? 26 : 0);
      targetH = baseEmpty;
      if (hasMessages) {
        const contentH = $("messagesContainer").scrollHeight || 100;
        targetH = Math.min(prefMaxH, Math.max(240, contentH + (isWork ? 186 : 158) + (hasAtts ? 26 : 0)));
      }
    }
    if (Math.abs(targetH - state.lastHeightSent) >= 6 || targetW !== state.lastWidthSent) {
      state.lastWidthSent = targetW;
      state.lastHeightSent = targetH;
      fetch("/api/desktop/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "resize", width: targetW, height: targetH }),
      }).catch(() => {});
    }
  }

  async function refreshCliSessions() {
    try {
      state.cliSessions = await api("/api/kimi-cli/sessions");
      renderSidebarList();
    } catch (_) {
      state.cliSessions = [];
    }
  }

  function getCurrentRun() {
    if (state.activeConvId && state.runs[state.activeConvId]) {
      return state.runs[state.activeConvId];
    }
    if (!state.activeConvId && state.viewRunKey && state.runs[state.viewRunKey]) {
      return state.runs[state.viewRunKey];
    }
    return null;
  }

  function isViewingRun(runObj) {
    if (!runObj) return false;
    if (state.activeConvId) return runObj.convId === state.activeConvId;
    return !!state.viewRunKey && runObj.convId === state.viewRunKey;
  }

  function syncComposerButtons() {
    const curRun = getCurrentRun();
    const btnSend = $("btnSend");
    const btnStop = $("btnStop");
    if (btnSend) btnSend.classList.toggle("hidden", !!curRun);
    if (btnStop) {
      btnStop.classList.toggle("hidden", !curRun);
      btnStop.disabled = !!(curRun && curRun.stopping);
      btnStop.textContent = curRun && curRun.stopping ? "停止中" : "停止";
    }

    const activeRuns = Object.values(state.runs);
    const hasWorkRun = activeRuns.some((r) => r.mode !== "chat");
    const hasChatRun = activeRuns.some((r) => r.mode === "chat");
    document.querySelectorAll('[data-mode-dot="work"]').forEach((el) => {
      el.classList.toggle("hidden", !hasWorkRun);
    });
    document.querySelectorAll('[data-mode-dot="chat"]').forEach((el) => {
      el.classList.toggle("hidden", !hasChatRun);
    });
  }

  function ensureElapsedTicker() {
    const hasAny = Object.keys(state.runs).length > 0;
    if (!hasAny) {
      if (state.elapsedTimer) {
        clearInterval(state.elapsedTimer);
        state.elapsedTimer = null;
      }
      return;
    }
    if (state.elapsedTimer) return;
    state.elapsedTimer = setInterval(() => {
      if (!Object.keys(state.runs).length) {
        clearInterval(state.elapsedTimer);
        state.elapsedTimer = null;
        return;
      }
      document.querySelectorAll("[data-run-elapsed]").forEach((el) => {
        const started = Number(el.dataset.runElapsed || 0);
        if (!started) return;
        const sec = Math.max(0, Math.floor((Date.now() - started) / 1000));
        const prefix = el.dataset.runPrefix || "";
        el.textContent = `${prefix}${sec}s`;
      });
    }, 1000);
  }

  function hydrateActiveRunFromSnapshot(snap) {
    if (!snap || !snap.conversation_id || snap.done) return null;
    const cid = snap.conversation_id;
    let runObj = state.runs[cid];
    const startedMs = snap.started_at ? Math.round(Number(snap.started_at) * 1000) : Date.now();
    if (!runObj) {
      const assistantMsg = {
        id: "run_" + cid,
        role: "assistant",
        content: snap.content || "",
        reasoning: snap.reasoning || "",
        reasoning_seconds: snap.reasoning_seconds || 0,
        sources: snap.sources || [],
        steps: Array.isArray(snap.steps) ? snap.steps.map((s) => ({ ...s })) : [],
        model: snap.model || state.settings.active_model || "",
        _streaming: true,
        _streamingReasoning: !snap.content,
        _status: snap.status_label || "正在执行中...",
        _startedAt: startedMs,
      };
      runObj = {
        convId: cid,
        mode: snap.mode === "chat" ? "chat" : "work",
        startedAt: startedMs,
        statusLabel: snap.status_label || "正在执行中...",
        steps: assistantMsg.steps,
        assistantMsg,
        stopping: !!snap.stopped,
        attached: false,
      };
      state.runs[cid] = runObj;
    } else {
      runObj.statusLabel = snap.status_label || runObj.statusLabel;
      runObj.startedAt = startedMs;
      runObj.assistantMsg._startedAt = startedMs;
      runObj.assistantMsg._status = runObj.statusLabel;
      if (Array.isArray(snap.steps)) {
        runObj.steps = snap.steps.map((s) => ({ ...s }));
        runObj.assistantMsg.steps = runObj.steps;
      }
      if (typeof snap.content === "string") runObj.assistantMsg.content = snap.content;
      if (typeof snap.reasoning === "string") runObj.assistantMsg.reasoning = snap.reasoning;
      if (Array.isArray(snap.sources)) runObj.assistantMsg.sources = snap.sources;
    }
    return runObj;
  }

  async function syncActiveRunsFromServer() {
    try {
      const res = await api("/api/runs/active");
      const list = Array.isArray(res.runs) ? res.runs : [];
      const liveIds = new Set();
      for (const snap of list) {
        liveIds.add(snap.conversation_id);
        const runObj = hydrateActiveRunFromSnapshot(snap);
        if (runObj && !runObj.attached) {
          attachToRun(runObj.convId);
        }
      }
      for (const cid of Object.keys(state.runs)) {
        if (!cid.startsWith("__pending_") && !liveIds.has(cid) && !state.runs[cid].attached) {
          delete state.runs[cid];
        }
      }
      ensureElapsedTicker();
      syncComposerButtons();
      renderSidebarList();
    } catch (_) {}
  }

  async function bootstrap() {
    const data = await api("/api/bootstrap");
    state.appVersion = data.app_version || "1.2.0";
    state.repoUrl = data.repo_url || "https://github.com/tjcisyourdady-gif/YuiDesk";
    state.settings = data.settings;
    state.providers = data.providers;
    state.personas = data.personas;
    state.skins = data.skins;
    state.conversations = data.conversations;
    state.kimiCliStatus = data.kimi_cli_status || { installed: false, message: "" };
    state.activeMode = state.settings.active_mode === "chat" ? "chat" : "work";
    state.sidebarOpen = state.settings.sidebar_open !== false;
    state.historyFilterMode = state.activeMode;

    if (Array.isArray(data.active_runs)) {
      for (const snap of data.active_runs) {
        const runObj = hydrateActiveRunFromSnapshot(snap);
        if (runObj && !runObj.attached) attachToRun(runObj.convId);
      }
    }

    applyTheme(state.settings.theme || "light");
    applyDialogFontSize(state.settings.dialog_font_size ?? 11.5);
    renderModeUI();
    renderProjectSelect();
    renderPermissionSelect();
    renderUnifiedModelSelect();
    renderEffortSelect();
    renderPersonaSelect();
    renderConversations();
    renderMessages();
    syncComposerButtons();
    ensureElapsedTicker();
    refreshCliSessions();

    // 启动后 2.5 秒静默检查一次是否有新版本（仅提示，绝不自动下载或安装）
    setTimeout(() => {
      api("/api/update/check", { method: "POST" })
        .then((st) => {
          state.updateInfo = st;
          renderUpdateUI(st);
        })
        .catch(() => {});
    }, 2500);
  }

  function getCurrentMemoryMode() {
    const key = state.activeMode === "chat" ? "chat_memory_mode" : "work_memory_mode";
    const def = state.activeMode === "chat" ? "long_term" : "session";
    return state.settings[key] || def;
  }

  function renderMemorySelect() {
    const sel = $("memoryModeSelect");
    if (!sel) return;
    sel.value = getCurrentMemoryMode();
  }

  function renderSidebarList() {
    const list = $("sidebarConvList");
    if (!list) return;
    const isChat = state.activeMode === "chat";
    const q = (state.sidebarQuery || "").trim().toLowerCase();

    const items = state.conversations.filter((c) => {
      if (((c.mode || "work") === "chat") !== isChat) return false;
      if (!q) return true;
      return (c.title || "").toLowerCase().includes(q) || (c.project_dir || "").toLowerCase().includes(q);
    });

    if ($("sidebarListTitle")) $("sidebarListTitle").textContent = isChat ? "对话" : "任务";
    if ($("sidebarListCount")) $("sidebarListCount").textContent = String(items.length);
    if ($("btnSidebarNew")) $("btnSidebarNew").textContent = isChat ? "+ 新建会话" : "+ 新建任务";
    if ($("sidebarSearch")) $("sidebarSearch").placeholder = isChat ? "查找对话..." : "查找任务...";

    list.innerHTML = "";
    if (!items.length) {
      const empty = document.createElement("div");
      empty.style.cssText = "padding:10px 8px;font-size:11.5px;color:var(--muted);text-align:center;";
      empty.textContent = q ? "未找到匹配记录" : (isChat ? "暂无聊天记录" : "暂无工作任务记录");
      list.appendChild(empty);
    } else {
      for (const c of items) {
        const run = state.runs[c.id];
        const row = document.createElement("div");
        row.className =
          "sb-item" +
          (c.id === state.activeConvId ? " active" : "") +
          (run ? " running" : "");
        const projName = !isChat && c.project_dir ? c.project_dir.split(/[\\/]/).filter(Boolean).pop() : "";
        const subText = run
          ? (run.statusLabel || "正在运行中...")
          : projName;
        row.innerHTML = `
          ${run ? '<span class="sb-spinner" title="正在运行"></span>' : ""}
          <div class="sb-item-main">
            <div class="sb-item-title">${escapeHtml(c.title)}</div>
            ${subText ? `<div class="sb-item-sub" title="${escapeHtml(subText)}">${escapeHtml(subText)}</div>` : ""}
          </div>
          <button class="sb-item-del" title="删除">×</button>
        `;
        row.addEventListener("click", (e) => {
          if (e.target.classList.contains("sb-item-del")) {
            e.stopPropagation();
            deleteConversation(c.id);
          } else {
            selectConversation(c.id);
          }
        });
        list.appendChild(row);
      }
    }

    // 工作模式下，补充展示本机 Kimi Code CLI 已有但尚未收录进桌宠的任务会话，点一下即可续接
    if (!isChat && state.cliSessions.length) {
      const boundIds = new Set(state.conversations.map((c) => c.cli_session_id).filter(Boolean));
      const extraCli = state.cliSessions.filter((s) => {
        if (boundIds.has(s.session_id)) return false;
        if (!q) return true;
        return (s.title || "").toLowerCase().includes(q) || (s.folder || "").toLowerCase().includes(q);
      });
      if (extraCli.length) {
        const grp = document.createElement("div");
        grp.className = "sb-group-label";
        grp.textContent = `本机 Kimi 任务 (${extraCli.length})`;
        list.appendChild(grp);
        for (const s of extraCli.slice(0, 10)) {
          const row = document.createElement("div");
          row.className = "sb-item";
          row.innerHTML = `
            <div class="sb-item-main">
              <div class="sb-item-title">${escapeHtml(s.title)}</div>
              <div class="sb-item-sub">${escapeHtml(s.folder || "默认工作区")}</div>
            </div>
          `;
          row.onclick = async () => {
            try {
              const conv = await api("/api/kimi-cli/sessions/open", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: s.session_id, title: s.title, work_dir: s.work_dir }),
              });
              state.conversations = await api("/api/conversations");
              await selectConversation(conv.id);
              showToast(`已载入任务记忆：${s.title}`, 1800);
            } catch (err) {
              showToast("载入失败：" + err.message, 2500);
            }
          };
          list.appendChild(row);
        }
      }
    }
  }

  function renderModeUI() {
    const isChat = state.activeMode === "chat";
    const sidebar = $("dialogSidebar");
    if (sidebar) sidebar.classList.toggle("hidden", !state.sidebarOpen);
    const compactSwitch = $("compactModeSwitch");
    if (compactSwitch) compactSwitch.classList.toggle("hidden", state.sidebarOpen);
    const toggleBtn = $("btnToggleSidebar");
    if (toggleBtn) toggleBtn.textContent = state.sidebarOpen ? "收起栏" : "记录栏";

    for (const id of ["modeWorkBtn", "modeWorkBtnCompact"]) {
      if ($(id)) $(id).classList.toggle("active", !isChat);
    }
    for (const id of ["modeChatBtn", "modeChatBtnCompact"]) {
      if ($(id)) $(id).classList.toggle("active", isChat);
    }
    const metaRow = $("workMetaRow");
    if (metaRow) metaRow.classList.toggle("hidden", isChat);

    const activeConv = state.conversations.find((c) => c.id === state.activeConvId);
    const titleEl = $("activeConvTitle");
    if (titleEl) {
      titleEl.textContent = activeConv ? activeConv.title : (isChat ? "新聊天" : "新工作任务");
    }
    if ($("emptyStageTitle")) $("emptyStageTitle").textContent = isChat ? "聊天模式" : "工作模式";
    if ($("emptyStageSub")) {
      $("emptyStageSub").textContent = isChat
        ? "点击左侧历史对话续接记忆，或直接随便聊聊"
        : "点击左侧历史任务续接记忆，或直接输入新任务";
    }

    renderMemorySelect();
    renderSidebarList();
    const inp = $("chatInput");
    if (inp) {
      inp.placeholder = isChat
        ? "聊天模式：随便聊聊，Enter 发送（与项目记录独立保存）"
        : "工作模式：输入开发或文档任务，Enter 发送（支持拖入文件到桌宠）";
    }
    syncDialogHeight();
  }

  async function toggleSidebar() {
    state.sidebarOpen = !state.sidebarOpen;
    renderModeUI();
    renderMessages();
    state.settings = await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sidebar_open: state.sidebarOpen }),
    });
  }

  async function switchDialogMode(nextMode) {
    const clean = nextMode === "chat" ? "chat" : "work";
    if (clean === state.activeMode) return;
    state.modeConvIds[state.activeMode] = state.activeConvId;
    state.activeMode = clean;
    state.historyFilterMode = clean;
    state.viewRunKey = null;

    const targetConvId = state.modeConvIds[clean];
    if (targetConvId && state.conversations.some((c) => c.id === targetConvId && (c.mode || "work") === clean)) {
      await selectConversation(targetConvId, true);
    } else {
      state.activeConvId = null;
      state.messages = [];
      renderModeUI();
      renderConversations();
      renderMessages();
      syncComposerButtons();
    }

    state.settings = await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active_mode: clean }),
    });
    showToast(clean === "chat" ? "已切换：聊天模式（后台任务继续运行）" : "已切换：工作模式", 1500);
  }

  function renderProjectSelect() {
    const sel = $("projectSelect");
    if (!sel) return;
    sel.innerHTML = "";
    const activeDir = state.settings.active_project_dir || "";
    const recent = Array.isArray(state.settings.recent_projects) ? state.settings.recent_projects : [];

    const defOpt = document.createElement("option");
    defOpt.value = "";
    defOpt.textContent = "项目：默认工作区";
    if (!activeDir) defOpt.selected = true;
    sel.appendChild(defOpt);

    const list = [...recent];
    if (activeDir && !list.includes(activeDir)) list.unshift(activeDir);
    for (const dir of list) {
      const name = dir.split(/[\\/]/).filter(Boolean).pop() || dir;
      const opt = document.createElement("option");
      opt.value = dir;
      opt.textContent = `项目：${name}`;
      opt.title = dir;
      if (dir === activeDir) opt.selected = true;
      sel.appendChild(opt);
    }

    const pickOpt = document.createElement("option");
    pickOpt.value = "__pick__";
    pickOpt.textContent = "+ 选择项目文件夹...";
    sel.appendChild(pickOpt);
    sel.title = activeDir || "默认工作区";
  }

  function renderPermissionSelect() {
    const sel = $("permissionSelect");
    if (!sel) return;
    sel.value = state.settings.permission_level || "standard";
  }

  function applyTheme(theme) {
    document.body.classList.toggle("theme-dark", theme === "dark");
    document.body.classList.toggle("theme-light", theme !== "dark");
  }

  function renderUnifiedModelSelect() {
    const sel = $("topModelUnified");
    sel.innerHTML = "";
    const activePid = state.settings.active_provider_id || "kimi_cli";
    const activeModel = state.settings.active_model || "default";
    const activeProvider = state.providers.find((p) => p.id === activePid) || state.providers[0];
    if (!activeProvider) return;

    const models = [...(activeProvider.models || [])];
    if (activeModel && !models.includes(activeModel)) models.unshift(activeModel);

    for (const m of models) {
      const opt = document.createElement("option");
      opt.value = `${activeProvider.id}::${m}`;
      opt.textContent = m === "default" ? "Kimi 默认旗舰" : m;
      if (m === activeModel) opt.selected = true;
      sel.appendChild(opt);
    }
  }

  function renderEffortSelect() {
    $("effortSelect").value = state.settings.thinking_enabled
      ? (state.settings.reasoning_effort || "medium")
      : "off";
  }

  function renderPersonaSelect() {
    const sel = $("personaSelect");
    if (!sel) return;
    sel.innerHTML = "";
    for (const p of state.personas) {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name;
      if (p.id === state.settings.active_persona_id) opt.selected = true;
      sel.appendChild(opt);
    }
  }

  function renderConversations() {
    const list = $("convList");
    if (!list) return;
    const workConvs = state.conversations.filter((c) => (c.mode || "work") !== "chat");
    const chatConvs = state.conversations.filter((c) => (c.mode || "work") === "chat");

    const tabW = $("histTabWork");
    const tabC = $("histTabChat");
    if (tabW) {
      tabW.textContent = `项目记录 (${workConvs.length})`;
      tabW.classList.toggle("active", state.historyFilterMode !== "chat");
    }
    if (tabC) {
      tabC.textContent = `聊天记录 (${chatConvs.length})`;
      tabC.classList.toggle("active", state.historyFilterMode === "chat");
    }

    const filtered = state.historyFilterMode === "chat" ? chatConvs : workConvs;
    list.innerHTML = "";
    if (!filtered.length) {
      list.innerHTML = `<div style="color:var(--muted);font-size:12px;">${
        state.historyFilterMode === "chat" ? "暂无聊天记录" : "暂无项目记录"
      }</div>`;
      return;
    }
    for (const c of filtered) {
      const div = document.createElement("div");
      div.className = "conv-item" + (c.id === state.activeConvId ? " active" : "");
      const projLabel =
        (c.mode || "work") !== "chat" && c.project_dir
          ? `<span class="conv-meta-tag">${escapeHtml(c.project_dir.split(/[\\/]/).filter(Boolean).pop() || "")}</span>`
          : "";
      div.innerHTML = `<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;">${escapeHtml(c.title)}${projLabel}</span><button class="conv-del">删除</button>`;
      div.addEventListener("click", (e) => {
        if (e.target.classList.contains("conv-del")) {
          e.stopPropagation();
          deleteConversation(c.id);
        } else {
          selectConversation(c.id);
        }
      });
      list.appendChild(div);
    }
    renderSidebarList();
  }

  async function selectConversation(convId, skipCloseSettings = false) {
    const conv = state.conversations.find((c) => c.id === convId);
    const targetMode = conv && (conv.mode || "work") === "chat" ? "chat" : "work";
    state.activeMode = targetMode;
    state.activeConvId = convId;
    state.viewRunKey = null;
    state.modeConvIds[targetMode] = convId;

    // 同步后端仍在运行的后台任务，确保切换项目再切回时绝不丢失运行中图标与实时进度
    await syncActiveRunsFromServer();
    const dbMsgs = await api(`/api/conversations/${convId}/messages`);
    const activeRun = state.runs[convId];
    if (activeRun && activeRun.assistantMsg) {
      state.messages = [...dbMsgs, activeRun.assistantMsg];
      if (!activeRun.attached) {
        attachToRun(convId);
      }
    } else {
      state.messages = dbMsgs;
    }

    if (!skipCloseSettings && !$("settingsModal").classList.contains("hidden")) {
      $("settingsModal").classList.add("hidden");
      state.settingsOnlyWindow = false;
      fetch("/api/desktop/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "dialog" }),
      }).catch(() => {});
    }
    renderModeUI();
    renderConversations();
    renderMessages();
    syncComposerButtons();
  }

  function createNewChat() {
    state.activeConvId = null;
    state.viewRunKey = null;
    state.modeConvIds[state.activeMode] = null;
    state.messages = [];
    state.pendingAttachments = [];
    renderAttachmentsBar();
    renderModeUI();
    renderMessages();
    syncComposerButtons();
    $("chatInput").focus();
  }

  async function deleteConversation(convId) {
    await api(`/api/conversations/${convId}`, { method: "DELETE" });
    delete state.runs[convId];
    if (state.activeConvId === convId) {
      state.activeConvId = null;
      state.viewRunKey = null;
      state.messages = [];
    }
    state.conversations = await api("/api/conversations");
    renderConversations();
    renderMessages();
    syncComposerButtons();
  }

  function renderMessages() {
    const section = $("replySection");
    const emptyStage = $("emptyStage");
    const container = $("messagesContainer");
    if (!state.messages.length) {
      section.classList.add("hidden");
      if (emptyStage) emptyStage.classList.toggle("hidden", !state.sidebarOpen);
      container.innerHTML = "";
      $("replyStatus").textContent = "";
      syncDialogHeight();
      return;
    }
    if (emptyStage) emptyStage.classList.add("hidden");
    section.classList.remove("hidden");
    container.innerHTML = "";
    let activeStatus = "";
    for (const msg of state.messages) {
      if (msg._status) activeStatus = msg._status;
      container.appendChild(buildMessageElement(msg));
    }
    $("replyStatus").textContent = activeStatus;
    const sc = $("chatScroll");
    sc.scrollTop = sc.scrollHeight;
    requestAnimationFrame(syncDialogHeight);
  }

  function buildMessageElement(msg) {
    const row = document.createElement("div");
    row.className = `msg-row ${msg.role}`;

    if (msg.attachments && msg.attachments.length) {
      const attWrap = document.createElement("div");
      attWrap.className = "msg-attachments";
      for (const att of msg.attachments) {
        if (att.kind === "image" && att.local_path) {
          const fname = att.local_path.split(/[\\/]/).pop();
          const img = document.createElement("img");
          img.className = "att-thumb";
          img.src = `/api/uploads/${encodeURIComponent(fname)}`;
          attWrap.appendChild(img);
        } else {
          const badge = document.createElement("div");
          badge.className = "att-badge";
          badge.textContent = `${att.name} (${att.chars || 0}字)`;
          attWrap.appendChild(badge);
        }
      }
      row.appendChild(attWrap);
    }

    if (msg.sources && msg.sources.length) {
      const sbar = document.createElement("div");
      sbar.className = "sources-bar";
      for (const s of msg.sources) {
        const a = document.createElement("a");
        a.className = "source-chip";
        a.href = s.url;
        a.target = "_blank";
        a.textContent = `[${s.index || "-"}] ${s.title || s.url}`;
        sbar.appendChild(a);
      }
      row.appendChild(sbar);
    }

    if (msg.reasoning) {
      const details = document.createElement("details");
      details.className = "reasoning-box";
      if (msg._streamingReasoning) details.open = true;
      const secText = msg.reasoning_seconds ? ` (${msg.reasoning_seconds}s)` : "";
      details.innerHTML = `<summary>思考过程${secText}</summary><div class="reasoning-content">${escapeHtml(msg.reasoning)}</div>`;
      row.appendChild(details);
    }

    const steps = Array.isArray(msg.steps) ? msg.steps : [];
    const showStepsCard = msg.role === "assistant" && (steps.length > 0 || msg._streaming);
    if (showStepsCard) {
      const box = document.createElement("details");
      box.className = "steps-box" + (msg._streaming ? " is-running" : "");
      if (msg._streaming) box.open = true;

      const toolSteps = steps.filter((s) => s.status !== "note");
      const doneCount = toolSteps.filter((s) => s.status === "done").length;
      const activeStep = [...steps].reverse().find((s) => s.status === "running");
      const headTitle = msg._streaming
        ? (activeStep?.title || msg._status || "正在执行任务...")
        : `已执行 ${toolSteps.length || steps.length} 个阶段步骤`;

      let metaHtml = "";
      if (msg._streaming) {
        const started = msg._startedAt || Date.now();
        const elapsed = Math.max(0, Math.floor((Date.now() - started) / 1000));
        const prefix = toolSteps.length ? `第 ${Math.min(doneCount + 1, toolSteps.length)}/${toolSteps.length} 步 · ` : "";
        metaHtml = `<span class="steps-head-meta" data-run-elapsed="${started}" data-run-prefix="${escapeHtml(prefix)}">${escapeHtml(prefix)}${elapsed}s</span>`;
      } else {
        metaHtml = `<span class="steps-head-meta">点击展开</span>`;
      }

      const headIcon = msg._streaming
        ? '<span class="step-spinner"></span>'
        : '<span class="step-icon done">✓</span>';

      const listHtml = steps.length
        ? steps
            .map((s) => {
              const st = s.status || "done";
              let iconHtml = '<span class="step-icon done">✓</span>';
              if (st === "running") iconHtml = '<span class="step-icon"><span class="step-spinner"></span></span>';
              else if (st === "error") iconHtml = '<span class="step-icon error">✕</span>';
              else if (st === "stopped") iconHtml = '<span class="step-icon stopped">■</span>';
              else if (st === "note") iconHtml = '<span class="step-icon note">•</span>';
              return `
                <div class="step-row ${escapeHtml(st)}">
                  ${iconHtml}
                  <div class="step-body">
                    <div class="step-title">${escapeHtml(s.title || "")}</div>
                    ${s.summary ? `<div class="step-summary" title="${escapeHtml(s.summary)}">${escapeHtml(s.summary)}</div>` : ""}
                  </div>
                </div>
              `;
            })
            .join("")
        : `
          <div class="step-row running">
            <span class="step-icon"><span class="step-spinner"></span></span>
            <div class="step-body">
              <div class="step-title">${escapeHtml(msg._status || "正在分析任务并调度工具...")}</div>
            </div>
          </div>
        `;

      box.innerHTML = `
        <summary>
          ${headIcon}
          <span class="steps-head-title" title="${escapeHtml(headTitle)}">${escapeHtml(headTitle)}</span>
          ${metaHtml}
        </summary>
        <div class="steps-list">${listHtml}</div>
      `;
      row.appendChild(box);
    }

    const shouldRenderBubble =
      msg.role === "user" || !msg._streaming || Boolean((msg.content || "").trim());
    if (shouldRenderBubble) {
      const bubble = document.createElement("div");
      bubble.className = "msg-bubble md-content";
      if (msg.role === "user") {
        bubble.innerHTML = escapeHtml(msg.content || "").replace(/\n/g, "<br>");
      } else {
        bubble.innerHTML = renderMarkdown(msg.content || "");
      }
      row.appendChild(bubble);
    }

    if (msg.role === "assistant" && !msg._streaming) {
      const acts = document.createElement("div");
      acts.className = "msg-actions";
      acts.innerHTML = `
        <button class="msg-action-btn" data-act="copy">复制</button>
        <button class="msg-action-btn" data-act="regen">重试</button>
      `;
      acts.addEventListener("click", (e) => {
        const act = e.target?.dataset?.act;
        if (act === "copy") {
          navigator.clipboard.writeText(msg.content || "");
          showToast("已复制");
        } else if (act === "regen") {
          regenerateMessage(msg.id);
        }
      });
      row.appendChild(acts);
    }
    return row;
  }

  function renderAttachmentsBar() {
    const bar = $("attachmentBar");
    if (!state.pendingAttachments.length) {
      bar.classList.add("hidden");
      bar.innerHTML = "";
      syncDialogHeight();
      return;
    }
    bar.classList.remove("hidden");
    bar.innerHTML = "";
    state.pendingAttachments.forEach((att, idx) => {
      const chip = document.createElement("div");
      chip.className = "att-chip";
      if (att.kind === "image" && att.local_path) {
        const fname = att.local_path.split(/[\\/]/).pop();
        chip.innerHTML = `<img src="/api/uploads/${encodeURIComponent(fname)}" /><span>${escapeHtml(att.name)}</span>`;
      } else {
        chip.innerHTML = `<span>${escapeHtml(att.name)}</span>`;
      }
      const btn = document.createElement("button");
      btn.className = "att-remove";
      btn.textContent = "×";
      btn.onclick = () => {
        state.pendingAttachments.splice(idx, 1);
        renderAttachmentsBar();
      };
      chip.appendChild(btn);
      bar.appendChild(chip);
    });
    syncDialogHeight();
  }

  async function uploadFiles(fileList) {
    for (const file of fileList) {
      const form = new FormData();
      form.append("file", file);
      form.append("provider_id", state.settings.active_provider_id || "");
      showToast(`正在读取 ${file.name}`);
      try {
        const res = await api("/api/upload", { method: "POST", body: form });
        if (res.attachment) {
          state.pendingAttachments.push(res.attachment);
          renderAttachmentsBar();
        }
      } catch (err) {
        showToast("上传失败：" + err.message, 3000);
      }
    }
  }

  async function consumeRunStream(runObj, readableBody) {
    const reader = readableBody.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let wasStopped = false;
    let hadError = false;

    const applyEvent = (ev) => {
      if (!ev || typeof ev !== "object") return;
      const msg = runObj.assistantMsg;

      if (ev.type === "meta") {
        const oldKey = runObj.convId;
        const realId = ev.conversation_id;
        if (realId && realId !== oldKey) {
          delete state.runs[oldKey];
          runObj.convId = realId;
          runObj.assistantMsg.id = "run_" + realId;
          state.runs[realId] = runObj;
          state.modeConvIds[ev.mode || runObj.mode] = realId;
          if (!state.activeConvId && state.viewRunKey === oldKey) {
            state.activeConvId = realId;
            state.viewRunKey = null;
          }
          // 立刻刷新侧栏列表，让新建运行中的任务马上亮起旋转图标
          api("/api/conversations")
            .then((convs) => {
              state.conversations = convs;
              renderConversations();
              renderModeUI();
              syncComposerButtons();
            })
            .catch(() => {});
        }
        return;
      }

      if (ev.type === "snapshot") {
        hydrateActiveRunFromSnapshot(ev);
      } else if (ev.type === "step_start" && ev.step) {
        const idx = runObj.steps.findIndex((s) => s.id === ev.step.id);
        if (idx >= 0) runObj.steps[idx] = ev.step;
        else runObj.steps.push(ev.step);
        msg.steps = runObj.steps;
        runObj.statusLabel = ev.step.title || runObj.statusLabel;
        msg._status = runObj.statusLabel;
      } else if (ev.type === "step_done") {
        const target =
          (ev.id && [...runObj.steps].reverse().find((s) => s.id === ev.id)) ||
          [...runObj.steps].reverse().find((s) => s.status === "running");
        if (target) {
          target.status = ev.ok === false ? "error" : "done";
          target.summary = ev.summary || (ev.ok === false ? "执行异常" : "已完成");
        }
        msg.steps = runObj.steps;
      } else if (ev.type === "step_note" && ev.step) {
        runObj.steps.push(ev.step);
        msg.steps = runObj.steps;
      } else if (ev.type === "status") {
        runObj.statusLabel = ev.label || runObj.statusLabel;
        msg._status = runObj.statusLabel;
      } else if (ev.type === "sources") {
        msg.sources = ev.sources || [];
      } else if (ev.type === "reasoning") {
        msg.reasoning += ev.delta || "";
      } else if (ev.type === "content") {
        msg._streamingReasoning = false;
        runObj.statusLabel = "正在输出回复...";
        msg._status = "";
        msg.content += ev.delta || "";
      } else if (ev.type === "stopped") {
        wasStopped = true;
        runObj.stopping = true;
        msg._status = "";
      } else if (ev.type === "error") {
        hadError = true;
        msg._status = "";
        msg.content += `\n\n> ${ev.message}`;
      } else if (ev.type === "saved" && ev.assistant_message) {
        Object.assign(msg, ev.assistant_message);
        if (Array.isArray(ev.assistant_message.steps)) {
          runObj.steps = ev.assistant_message.steps;
          msg.steps = runObj.steps;
        }
      } else if (ev.type === "run_end") {
        if (ev.stopped) wasStopped = true;
        if (ev.had_error) hadError = true;
      }

      if (isViewingRun(runObj)) {
        renderMessages();
      }
      renderSidebarList();
      syncComposerButtons();
    };

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const chunk of parts) {
          const line = chunk.trim();
          if (!line.startsWith("data:")) continue;
          let ev;
          try {
            ev = JSON.parse(line.slice(5).trim());
          } catch (_) {
            continue;
          }
          applyEvent(ev);
        }
      }
    } catch (err) {
      hadError = true;
      runObj.assistantMsg.content += `\n\n> ${err.message}`;
    } finally {
      const viewing = isViewingRun(runObj);
      runObj.attached = false;
      runObj.assistantMsg._streaming = false;
      runObj.assistantMsg._streamingReasoning = false;
      runObj.assistantMsg._status = "";
      if (state.runs[runObj.convId] === runObj) {
        delete state.runs[runObj.convId];
      }
      if (state.viewRunKey === runObj.convId) {
        state.viewRunKey = null;
      }

      ensureElapsedTicker();
      syncComposerButtons();

      try {
        state.conversations = await api("/api/conversations");
      } catch (_) {}

      if (viewing) {
        // 若正在查看该会话，重新渲染并刷新最终落库消息
        if (state.activeConvId && !state.activeConvId.startsWith("__pending_")) {
          try {
            state.messages = await api(`/api/conversations/${state.activeConvId}/messages`);
          } catch (_) {}
        }
        renderMessages();
      } else {
        const conv = state.conversations.find((c) => c.id === runObj.convId);
        const name = conv ? conv.title : (runObj.mode === "chat" ? "聊天" : "任务");
        showToast(
          wasStopped
            ? `后台任务已停止：${name}`
            : (hadError ? `后台任务结束（有异常）：${name}` : `后台任务已完成：${name}`),
          2200
        );
      }

      renderConversations();
      renderModeUI();
      syncComposerButtons();
      refreshCliSessions();
    }
  }

  async function attachToRun(convId) {
    const runObj = state.runs[convId];
    if (!runObj || runObj.attached) return;
    runObj.attached = true;
    try {
      const resp = await fetch(`/api/runs/${encodeURIComponent(convId)}/stream`);
      if (!resp.ok || !resp.body) {
        runObj.attached = false;
        delete state.runs[convId];
        syncComposerButtons();
        renderSidebarList();
        return;
      }
      await consumeRunStream(runObj, resp.body);
    } catch (_) {
      runObj.attached = false;
    }
  }

  async function stopCurrentRun() {
    const curRun = getCurrentRun();
    if (!curRun || curRun.stopping) return;
    curRun.stopping = true;
    syncComposerButtons();

    // 若刚点发送不足百毫秒还没拿到真实 conv_id，短暂等待 meta 返回
    let targetId = curRun.convId;
    for (let i = 0; i < 15 && targetId.startsWith("__pending_"); i++) {
      await new Promise((r) => setTimeout(r, 100));
      targetId = curRun.convId;
    }

    if (!targetId || targetId.startsWith("__pending_")) {
      curRun.stopping = false;
      syncComposerButtons();
      return;
    }

    try {
      showToast("正在停止当前任务...", 1500);
      await api(`/api/runs/${encodeURIComponent(targetId)}/stop`, { method: "POST" });
    } catch (err) {
      curRun.stopping = false;
      syncComposerButtons();
      showToast("停止失败：" + err.message, 2500);
    }
  }

  async function sendMessage(overrideContent = null, regenerateFromId = null) {
    if (getCurrentRun()) {
      showToast("当前任务正在运行，可先切换聊天/其他项目或点击停止", 2000);
      return;
    }
    const input = $("chatInput");
    const content = overrideContent !== null ? overrideContent : input.value.trim();
    const attachments = regenerateFromId ? [] : [...state.pendingAttachments];
    if (!regenerateFromId && !content && !attachments.length) return;

    const sendMode = state.activeMode;
    const sendConvId = state.activeConvId;
    const startedAt = Date.now();

    if (!regenerateFromId) {
      input.value = "";
      state.pendingAttachments = [];
      renderAttachmentsBar();
      state.messages.push({ id: "u_" + startedAt, role: "user", content, attachments });
    }

    const runKey = sendConvId || ("__pending_" + startedAt);
    const assistantMsg = {
      id: "run_" + runKey,
      role: "assistant",
      content: "",
      reasoning: "",
      reasoning_seconds: 0,
      sources: [],
      steps: [],
      model: state.settings.active_model || "",
      _streaming: true,
      _streamingReasoning: true,
      _status: sendMode === "chat" ? "正在连接 Kimi..." : "正在启动任务引擎...",
      _startedAt: startedAt,
    };
    const runObj = {
      convId: runKey,
      mode: sendMode,
      startedAt,
      statusLabel: assistantMsg._status,
      steps: assistantMsg.steps,
      assistantMsg,
      stopping: false,
      attached: true,
    };

    state.runs[runKey] = runObj;
    if (!sendConvId) {
      state.viewRunKey = runKey;
    }
    state.messages.push(assistantMsg);
    renderMessages();
    renderSidebarList();
    syncComposerButtons();
    ensureElapsedTicker();

    try {
      const endpoint = sendMode === "chat" ? "/api/chat" : "/api/work";
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: sendConvId,
          content: regenerateFromId ? "" : content,
          attachments,
          provider_id: state.settings.active_provider_id,
          model: state.settings.active_model,
          persona_id: state.settings.active_persona_id,
          mode: sendMode,
          memory_mode: getCurrentMemoryMode(),
          project_dir: sendMode === "chat" ? "" : (state.settings.active_project_dir || ""),
          permission_level: state.settings.permission_level || "standard",
          web_search: !!state.settings.web_search_enabled,
          thinking: !!state.settings.thinking_enabled,
          reasoning_effort: state.settings.reasoning_effort || "medium",
          regenerate_from_message_id: regenerateFromId,
        }),
      });
      if (!resp.ok || !resp.body) {
        let errTxt = `HTTP ${resp.status}`;
        try {
          const j = await resp.json();
          errTxt = j.detail || j.message || errTxt;
        } catch (_) {}
        throw new Error(errTxt);
      }
      // 不阻塞 sendMessage 返回外的其他并发交互：异步消费该任务的独立流
      consumeRunStream(runObj, resp.body);
    } catch (err) {
      assistantMsg._streaming = false;
      assistantMsg._status = "";
      assistantMsg.content += `\n\n> ${err.message}`;
      delete state.runs[runKey];
      if (state.viewRunKey === runKey) state.viewRunKey = null;
      ensureElapsedTicker();
      syncComposerButtons();
      renderSidebarList();
      if (isViewingRun(runObj) || state.activeConvId === sendConvId) {
        renderMessages();
      }
    }
  }

  async function regenerateMessage(msgId) {
    if (!state.activeConvId || !msgId || msgId.startsWith("a_") || msgId.startsWith("run_")) return;
    if (getCurrentRun()) return;
    const idx = state.messages.findIndex((m) => m.id === msgId);
    if (idx >= 0) state.messages = state.messages.slice(0, idx);
    await sendMessage("", msgId);
  }

  // ---------- 设置弹窗 ----------
  function openSettings(defaultTab = "providers", settingsOnly = true) {
    state.settingsOnlyWindow = settingsOnly;
    $("settingsModal").classList.remove("hidden");
    switchSettingsTab(defaultTab);
    renderProviderManager();
    renderSkinManager();
    renderTimingSettings();
    renderPersonaManager();
    renderSystemSettings();
  }

  function renderTimingSettings() {
    const s = state.settings || {};
    $("petIdleIntervalSec").value = s.pet_idle_interval_sec ?? 10;
    $("petWalkDurationSec").value = s.pet_walk_duration_sec ?? 4;
    $("petSleepTimeoutMin").value = s.pet_sleep_timeout_min ?? 10;
    $("petBubbleDurationSec").value = s.pet_bubble_duration_sec ?? 4;
    $("carePollIntervalSec").value = s.care_poll_interval_sec ?? 60;
    $("aiTimeoutSec").value = s.ai_timeout_sec ?? 180;
    $("reminderEnabled").checked = !!s.reminder_enabled;
    $("reminderIntervalMin").value = s.reminder_interval_min ?? 45;
    $("reminderDailyTime").value = s.reminder_daily_time || "";
    $("reminderText").value = s.reminder_text || "已经专注一段时间啦，起来活动一下、喝口水吧";
  }

  async function closeSettings() {
    $("settingsModal").classList.add("hidden");
    if (state.settingsOnlyWindow) {
      state.settingsOnlyWindow = false;
      await api("/api/desktop/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "hide" }),
      });
    }
  }

  function switchSettingsTab(tabName) {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === tabName));
    document.querySelectorAll(".tab-pane").forEach((p) => p.classList.toggle("active", p.id === `tab-${tabName}`));
  }

  function renderProviderManager() {
    const cli = state.providers.find((p) => p.id === "kimi_cli");
    const apiP = state.providers.find((p) => p.id === "kimi_cn");
    const st = state.kimiCliStatus || {};

    const badge = $("kimiCliBadge");
    const isCliActive = state.settings.active_provider_id === "kimi_cli";
    const ready = !!st.installed && st.has_git_bash !== false;
    badge.textContent = ready
      ? (isCliActive ? "当前使用 · 已就绪" : "已检测到引擎")
      : (st.installed ? "缺少 Git 环境" : "未安装");
    badge.className = "status-chip" + (ready ? " ok" : "");
    if ($("btnKimiInstallGit")) {
      $("btnKimiInstallGit").classList.toggle("hidden", st.has_git_bash !== false);
    }
    $("kimiCliStatusBox").textContent = st.message || "点击刷新检测本机 Kimi 引擎";
    $("kimiCliPath").value = state.settings.kimi_cli_path || "";
    $("kimiCliModel").value = cli?.default_model || "default";
    $("kimiCliFeedback").textContent = "";

    const allModels = Array.from(new Set([...(cli?.models || []), ...(apiP?.models || [])]));
    $("peModelDatalist").innerHTML = allModels.map((m) => `<option value="${escapeHtml(m)}">`).join("");

    if (apiP) {
      $("peBaseUrl").value = apiP.base_url || "https://api.moonshot.cn/v1";
      $("peApiKey").value = "";
      const statusChip = $("peKeyStatus");
      if (apiP.has_api_key) {
        statusChip.textContent = `已加密保存 (${apiP.api_key_masked})`;
        statusChip.className = "status-chip ok";
      } else {
        statusChip.textContent = "未设置";
        statusChip.className = "status-chip";
      }
      $("peDefaultModel").value = apiP.default_model || "kimi-k2-0905-preview";
      $("peFeedback").textContent = "";
    }
    $("webSearchSwitch").checked = !!state.settings.web_search_enabled;
  }

  function renderSkinManager() {
    const grid = $("skinGrid");
    grid.innerHTML = "";
    for (const s of state.skins) {
      const card = document.createElement("div");
      card.className = "skin-card" + (s.id === state.settings.active_skin_id ? " active" : "");
      card.innerHTML = `<div class="skin-card-name">${escapeHtml(s.name)}</div><div class="skin-card-desc">${escapeHtml(s.description || "")}</div>`;
      card.onclick = async () => {
        state.settings = await api("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ active_skin_id: s.id }),
        });
        renderSkinManager();
        showToast("已切换外观：" + s.name);
      };
      grid.appendChild(card);
    }
    $("petScale").value = state.settings.pet_scale || 100;
    $("petScaleVal").textContent = `${state.settings.pet_scale || 100}%`;
    $("petOpacity").value = state.settings.pet_opacity || 100;
    $("petOpacityVal").textContent = `${state.settings.pet_opacity || 100}%`;
    const dw = Number(state.settings.dialog_width) || 496;
    const dh = Number(state.settings.dialog_max_height) || 400;
    const df = Number(state.settings.dialog_font_size) || 11.5;
    $("dialogWidth").value = dw;
    $("dialogWidthVal").textContent = `${dw}px`;
    $("dialogHeight").value = dh;
    $("dialogHeightVal").textContent = `${dh}px`;
    $("dialogFontSize").value = df;
    $("dialogFontSizeVal").textContent = `${df}px`;
    $("petAlwaysOnTop").checked = !!state.settings.pet_always_on_top;
    $("petEdgeHide").checked = state.settings.pet_edge_hide !== false;
    $("petAutoWalk").checked = state.settings.pet_auto_walk !== false;
    $("petIdleBubbles").checked = state.settings.pet_idle_bubbles !== false;
    $("eatRecycleBin").checked = !!state.settings.eat_moves_to_recycle_bin;

    // 按当前角色自动更新「动作预览」按钮名称（如小狐狸显示扑毛线球、盯小蝴蝶、翻肚皮等）
    const activeSkin = state.skins.find((s) => s.id === state.settings.active_skin_id);
    const labelMap = (activeSkin && activeSkin.state_labels) || {};
    const defaultLabels = {
      idle: "待机", hover: "打招呼", thinking: "思考", searching: "搜索",
      reading: "读文档", speaking: "弹吉他回复", happy: "开心", drag: "拎起",
      peek_right: "扒在边缘", pet_head: "摸摸头", eat_cake: "吃蛋糕",
      practice_guitar: "练吉他", study_desk: "认真学习", hungry: "饿肚子",
      stretch: "伸懒腰", walk_right: "自由散步", sit_swing: "坐下晃腿",
      music_dance: "听歌摇摆", shy_blush: "害羞捂脸", proud_pose: "得意叉腰",
      error: "出错", sleep: "打盹",
    };
    document.querySelectorAll("#animPreviewGrid [data-state]").forEach((btn) => {
      const st = btn.dataset.state;
      btn.textContent = labelMap[st] || defaultLabels[st] || btn.textContent;
    });
  }

  function renderPersonaManager() {
    $("workMemory").value = state.settings.work_memory || "";
    $("chatMemory").value = state.settings.chat_memory || "";
    $("workMemoryModeDefault").value = state.settings.work_memory_mode || "session";
    $("chatMemoryModeDefault").value = state.settings.chat_memory_mode || "long_term";
    renderPersonaSelect();
    const list = $("personaList");
    list.innerHTML = "";
    for (const p of state.personas) {
      const item = document.createElement("div");
      item.className = "persona-item";
      item.innerHTML = `
        <div>
          <div style="font-weight:600;font-size:12.5px;">${escapeHtml(p.name)}</div>
          <div style="font-size:11.5px;color:var(--muted);margin-top:3px;">${escapeHtml(p.prompt)}</div>
        </div>
        ${p.is_custom ? `<button class="btn-outline" data-del-persona="${p.id}">删除</button>` : ""}
      `;
      const delBtn = item.querySelector("[data-del-persona]");
      if (delBtn) {
        delBtn.onclick = async () => {
          await api(`/api/personas/${p.id}`, { method: "DELETE" });
          state.personas = await api("/api/personas");
          renderPersonaManager();
        };
      }
      list.appendChild(item);
    }
  }

  function renderUpdateUI(st) {
    const info = st || state.updateInfo || { current_version: state.appVersion, status: "idle" };
    const chip = $("updateVerChip");
    if (chip) {
      chip.textContent = info.has_update
        ? `v${info.current_version || state.appVersion} -> v${info.latest_version}`
        : `v${info.current_version || state.appVersion}`;
      chip.className = "status-chip" + (info.has_update || info.status === "ready" ? " ok" : "");
    }
    const repoLink = $("updateRepoLink");
    if (repoLink && (info.releases_url || state.repoUrl)) {
      repoLink.href = info.releases_url || `${state.repoUrl}/releases`;
    }

    const banner = $("updateBanner");
    if (banner) {
      const showBanner = !!info.has_update && (info.status === "available" || info.status === "ready");
      banner.classList.toggle("hidden", !showBanner);
      if (showBanner && $("updateBannerText")) {
        $("updateBannerText").textContent =
          info.status === "ready"
            ? `v${info.latest_version} 更新包已就绪，点击安装并重启`
            : `发现新版本 v${info.latest_version}（当前 v${info.current_version || state.appVersion}）`;
      }
    }

    const statusEl = $("updateStatusText");
    if (statusEl) {
      const sizeText = info.package_size ? ` · 约 ${(info.package_size / 1048576).toFixed(1)} MB` : "";
      const srcText = info.download_source
        ? `（节点：${info.download_source}）`
        : (info.metadata_source ? `（来源：${info.metadata_source}）` : "");
      if (info.status === "available") {
        statusEl.textContent = `发现新版本 v${info.latest_version}${sizeText}${srcText}`;
      } else if (info.status === "downloading") {
        const dlMB = ((info.downloaded_bytes || 0) / 1048576).toFixed(1);
        const totMB = info.total_bytes ? (info.total_bytes / 1048576).toFixed(1) : "?";
        const spd = Number(info.speed_bps || 0);
        const spdText = spd >= 1048576
          ? ` · ${(spd / 1048576).toFixed(2)} MB/s`
          : (spd >= 1024 ? ` · ${Math.round(spd / 1024)} KB/s` : "");
        statusEl.textContent = `${info.message || "正在下载..."} ${dlMB}/${totMB} MB (${info.progress_pct || 0}%)${spdText}`;
      } else if (info.status === "ready") {
        statusEl.textContent = `v${info.latest_version} 更新包已就绪${srcText}`;
      } else {
        statusEl.textContent = `当前版本：v${info.current_version || state.appVersion}${srcText}`;
      }
    }

    const notesBox = $("updateNotesBox");
    if (notesBox) {
      const hasNotes = !!(info.notes && info.has_update);
      notesBox.classList.toggle("hidden", !hasNotes);
      if (hasNotes) notesBox.textContent = info.notes;
    }

    const progWrap = $("updateProgressWrap");
    const progBar = $("updateProgressBar");
    if (progWrap && progBar) {
      const showProg = info.status === "downloading" || info.status === "ready";
      progWrap.classList.toggle("hidden", !showProg);
      progBar.style.width = `${Math.max(0, Math.min(100, Number(info.progress_pct) || 0))}%`;
    }

    const btnCheck = $("btnCheckUpdate");
    const btnDl = $("btnDownloadUpdate");
    const btnApply = $("btnApplyUpdate");
    if (btnCheck) btnCheck.disabled = info.status === "checking" || info.status === "downloading";
    if (btnDl) {
      btnDl.classList.toggle("hidden", !info.has_update || info.status === "ready");
      btnDl.disabled = info.status === "downloading";
      btnDl.textContent = info.status === "downloading" ? `下载中 ${info.progress_pct || 0}%` : "下载更新包";
    }
    if (btnApply) {
      btnApply.classList.toggle("hidden", info.status !== "ready");
    }

    const fb = $("updateFeedback");
    if (fb) {
      if (info.status === "error") {
        fb.className = "feedback-msg err";
        fb.textContent = info.message || "检查更新失败";
      } else if (info.status === "ready") {
        fb.className = "feedback-msg ok";
        fb.textContent = "SHA-256 安全校验通过，更新包已就绪。";
      } else if (info.status === "up_to_date") {
        fb.className = "feedback-msg ok";
        fb.textContent = info.message || `已是最新版本 v${state.appVersion}`;
      } else {
        fb.className = "feedback-msg";
        fb.textContent = "";
      }
    }
  }

  function startUpdateDownloadPolling() {
    if (state.updatePollTimer) clearInterval(state.updatePollTimer);
    state.updatePollTimer = setInterval(async () => {
      try {
        const st = await api("/api/update/status");
        state.updateInfo = st;
        renderUpdateUI(st);
        if (st.status !== "downloading") {
          clearInterval(state.updatePollTimer);
          state.updatePollTimer = null;
        }
      } catch (_) {
        clearInterval(state.updatePollTimer);
        state.updatePollTimer = null;
      }
    }, 500);
  }

  function renderSystemSettings() {
    $("hotkeyToggle").value = state.settings.hotkey_toggle || "Alt+Space";
    $("hotkeyScreenshot").value = state.settings.hotkey_screenshot || "Alt+S";
    $("launchAtStartup").checked = !!state.settings.launch_at_startup;
    renderConversations();
    api("/api/update/status")
      .then((st) => {
        state.updateInfo = st;
        renderUpdateUI(st);
      })
      .catch(() => renderUpdateUI(state.updateInfo));
  }

  function bindEvents() {
    $("btnNewChat").onclick = createNewChat;
    $("btnCloseSettings").onclick = closeSettings;
    $("modeWorkBtn").onclick = () => switchDialogMode("work");
    $("modeChatBtn").onclick = () => switchDialogMode("chat");
    $("modeWorkBtnCompact").onclick = () => switchDialogMode("work");
    $("modeChatBtnCompact").onclick = () => switchDialogMode("chat");
    $("btnToggleSidebar").onclick = () => toggleSidebar();
    $("btnSidebarNew").onclick = () => createNewChat();
    $("sidebarSearch").oninput = (e) => {
      state.sidebarQuery = e.target.value || "";
      renderSidebarList();
    };
    $("memoryModeSelect").onchange = async (e) => {
      const val = e.target.value;
      const key = state.activeMode === "chat" ? "chat_memory_mode" : "work_memory_mode";
      state.settings = await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [key]: val }),
      });
      const names = { none: "无记忆", session: "仅本次", long_term: "含长期记忆" };
      const prefix = state.activeMode === "chat" ? "聊天" : "项目";
      showToast(`${prefix}记忆：${names[val] || val}`, 1600);
    };
    $("histTabWork").onclick = () => {
      state.historyFilterMode = "work";
      renderConversations();
    };
    $("histTabChat").onclick = () => {
      state.historyFilterMode = "chat";
      renderConversations();
    };

    $("btnHideToPet").onclick = async () => {
      await api("/api/desktop/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "hide" }),
      });
    };

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (!$("settingsModal").classList.contains("hidden")) {
          closeSettings();
        } else {
          $("btnHideToPet").click();
        }
      }
    });

    $("btnTheme").onclick = async () => {
      const next = state.settings.theme === "dark" ? "light" : "dark";
      state.settings = await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ theme: next }),
      });
      applyTheme(next);
    };

    $("projectSelect").onchange = async (e) => {
      const val = e.target.value;
      if (val === "__pick__") {
        // 先恢复当前显示，再弹出原生文件夹选择器
        renderProjectSelect();
        await api("/api/desktop/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "pick_project" }),
        });
        return;
      }
      state.settings = await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active_project_dir: val }),
      });
      // 切换项目后开启干净的新工作会话，后台正在运行的其他项目任务不受影响
      state.activeConvId = null;
      state.viewRunKey = null;
      state.messages = [];
      renderProjectSelect();
      renderModeUI();
      renderMessages();
      syncComposerButtons();
      showToast(val ? `已切换项目：${val.split(/[\\/]/).filter(Boolean).pop()}` : "已切回默认工作区");
    };

    $("permissionSelect").onchange = async (e) => {
      const val = e.target.value;
      state.settings = await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ permission_level: val }),
      });
      const names = { readonly: "只读", standard: "标准", full: "完全" };
      showToast(`权限等级：${names[val] || val}`);
    };

    $("topModelUnified").onchange = async (e) => {
      const [pid, model] = e.target.value.split("::");
      state.settings = await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active_provider_id: pid, active_model: model }),
      });
    };

    $("effortSelect").onchange = async (e) => {
      const val = e.target.value;
      const updates = val === "off"
        ? { thinking_enabled: false }
        : { thinking_enabled: true, reasoning_effort: val };
      state.settings = await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      });
    };

    $("personaSelect").onchange = async (e) => {
      state.settings = await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active_persona_id: e.target.value }),
      });
      showToast("已切换人设");
    };

    $("webSearchSwitch").onchange = async (e) => {
      state.settings = await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ web_search_enabled: e.target.checked }),
      });
    };

    $("fileInput").onchange = async (e) => {
      if (e.target.files?.length) {
        await uploadFiles(e.target.files);
        e.target.value = "";
      }
    };

    $("btnSend").onclick = () => sendMessage();
    $("btnStop").onclick = () => stopCurrentRun();

    if ($("btnOpenUpdateFromBanner")) {
      $("btnOpenUpdateFromBanner").onclick = () => openSettings("system", false);
    }
    if ($("btnCheckUpdate")) {
      $("btnCheckUpdate").onclick = async () => {
        $("btnCheckUpdate").disabled = true;
        $("updateFeedback").className = "feedback-msg";
        $("updateFeedback").textContent = "正在连接官方更新源检查新版本...";
        try {
          const st = await api("/api/update/check", { method: "POST" });
          state.updateInfo = st;
          renderUpdateUI(st);
        } catch (err) {
          $("updateFeedback").className = "feedback-msg err";
          $("updateFeedback").textContent = "检查失败：" + err.message;
        } finally {
          $("btnCheckUpdate").disabled = false;
        }
      };
    }
    if ($("btnDownloadUpdate")) {
      $("btnDownloadUpdate").onclick = async () => {
        try {
          const st = await api("/api/update/download", { method: "POST" });
          state.updateInfo = st;
          renderUpdateUI(st);
          startUpdateDownloadPolling();
        } catch (err) {
          $("updateFeedback").className = "feedback-msg err";
          $("updateFeedback").textContent = "启动下载失败：" + err.message;
        }
      };
    }
    if ($("btnApplyUpdate")) {
      $("btnApplyUpdate").onclick = async () => {
        $("btnApplyUpdate").disabled = true;
        try {
          const res = await api("/api/update/apply", { method: "POST" });
          $("updateFeedback").className = "feedback-msg " + (res.ok ? "ok" : "err");
          $("updateFeedback").textContent = res.message || "";
          if (res.ok) showToast("正在应用更新并重启...", 3000);
          else $("btnApplyUpdate").disabled = false;
        } catch (err) {
          $("btnApplyUpdate").disabled = false;
          $("updateFeedback").className = "feedback-msg err";
          $("updateFeedback").textContent = "应用失败：" + err.message;
        }
      };
    }

    $("chatInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    $("chatInput").addEventListener("paste", async (e) => {
      const items = e.clipboardData?.items || [];
      const files = [];
      for (const it of items) {
        if (it.kind === "file") {
          const f = it.getAsFile();
          if (f) files.push(f);
        }
      }
      if (files.length) { e.preventDefault(); await uploadFiles(files); }
    });

    $("messagesContainer").addEventListener("click", (e) => {
      const btn = e.target.closest(".code-copy-btn");
      if (!btn) return;
      const idx = Number(btn.dataset.copyIdx);
      const raw = (window.__lastCodeBlocks || [])[idx] || btn.closest(".code-block-wrap").querySelector("pre").innerText;
      navigator.clipboard.writeText(raw);
      btn.textContent = "已复制";
      setTimeout(() => (btn.textContent = "复制"), 1400);
    });

    let dragCounter = 0;
    document.addEventListener("dragenter", (e) => {
      if (e.dataTransfer?.types?.includes("Files")) {
        dragCounter++;
        $("dropOverlay").classList.remove("hidden");
      }
    });
    document.addEventListener("dragleave", () => {
      dragCounter = Math.max(0, dragCounter - 1);
      if (dragCounter === 0) $("dropOverlay").classList.add("hidden");
    });
    document.addEventListener("dragover", (e) => e.preventDefault());
    document.addEventListener("drop", async (e) => {
      e.preventDefault();
      dragCounter = 0;
      $("dropOverlay").classList.add("hidden");
      if (e.dataTransfer?.files?.length) await uploadFiles(e.dataTransfer.files);
    });

    document.querySelectorAll(".tab-btn").forEach((b) => { b.onclick = () => switchSettingsTab(b.dataset.tab); });

    $("btnKimiCheck").onclick = async () => {
      const customPath = $("kimiCliPath").value.trim();
      state.kimiCliStatus = await api(`/api/kimi-cli/status?custom_path=${encodeURIComponent(customPath)}`);
      renderProviderManager();
      renderUnifiedModelSelect();
      $("kimiCliFeedback").className = "feedback-msg " + (state.kimiCliStatus.installed ? "ok" : "err");
      $("kimiCliFeedback").textContent = state.kimiCliStatus.message;
    };

    $("btnKimiInstallGit").onclick = async () => {
      const res = await api("/api/kimi-cli/action/install_git", { method: "POST" });
      $("kimiCliFeedback").className = "feedback-msg " + (res.ok ? "ok" : "err");
      $("kimiCliFeedback").textContent = res.message + "（安装完后点击「刷新检测」）";
    };

    $("btnKimiInstall").onclick = async () => {
      const res = await api("/api/kimi-cli/action/install", { method: "POST" });
      $("kimiCliFeedback").className = "feedback-msg " + (res.ok ? "ok" : "err");
      $("kimiCliFeedback").textContent = res.message + "（安装完后点击「刷新检测」）";
    };

    $("btnKimiLogin").onclick = async () => {
      const res = await api("/api/kimi-cli/action/login", { method: "POST" });
      $("kimiCliFeedback").className = "feedback-msg " + (res.ok ? "ok" : "err");
      $("kimiCliFeedback").textContent = res.message;
    };

    $("btnKimiSave").onclick = async () => {
      const customPath = $("kimiCliPath").value.trim();
      const model = $("kimiCliModel").value.trim() || "default";
      await api("/api/providers/kimi_cli", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ default_model: model }),
      });
      state.settings = await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kimi_cli_path: customPath,
          active_provider_id: "kimi_cli",
          active_model: model,
        }),
      });
      state.kimiCliStatus = await api(`/api/kimi-cli/status?custom_path=${encodeURIComponent(customPath)}`);
      state.providers = await api("/api/providers");
      renderProviderManager();
      renderUnifiedModelSelect();
      showToast("已设为 Kimi 本机引擎中转模式");
    };

    $("btnFetchModels").onclick = async () => {
      const fb = $("peFeedback");
      fb.className = "feedback-msg";
      fb.textContent = "正在拉取 Kimi 模型列表...";
      const res = await api("/api/providers/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider_id: "kimi_cn",
          base_url: $("peBaseUrl").value.trim(),
          api_key: $("peApiKey").value.trim() || null,
        }),
      });
      if (res.ok && res.models?.length) {
        state.providers = await api("/api/providers");
        renderProviderManager();
        renderUnifiedModelSelect();
        fb.className = "feedback-msg ok";
        fb.textContent = `已同步 ${res.models.length} 个 Kimi 模型`;
      } else {
        fb.className = "feedback-msg err";
        fb.textContent = `拉取失败：${res.message || "请检查 API Key"}`;
      }
    };

    $("btnTestProvider").onclick = async () => {
      const fb = $("peFeedback");
      fb.className = "feedback-msg";
      fb.textContent = "正在测试连接...";
      const res = await api("/api/providers/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider_id: "kimi_cn",
          base_url: $("peBaseUrl").value.trim(),
          api_key: $("peApiKey").value.trim() || null,
          model: $("peDefaultModel").value.trim(),
        }),
      });
      fb.className = "feedback-msg " + (res.ok ? "ok" : "err");
      fb.textContent = res.message;
    };

    $("btnSaveProvider").onclick = async () => {
      const payload = {
        name: "Kimi 官方 API",
        base_url: $("peBaseUrl").value.trim() || "https://api.moonshot.cn/v1",
        default_model: $("peDefaultModel").value.trim() || "kimi-k2-0905-preview",
      };
      const rawKey = $("peApiKey").value.trim();
      if (rawKey) payload.api_key = rawKey;
      await api("/api/providers/kimi_cn", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      state.settings = await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          active_provider_id: "kimi_cn",
          active_model: payload.default_model,
          onboarding_completed: true,
        }),
      });
      state.providers = await api("/api/providers");
      renderProviderManager();
      renderUnifiedModelSelect();
      showToast("已切换为 Kimi API 模式");
    };

    $("animPreviewGrid").addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-state]");
      if (!btn) return;
      await fetch(`/api/pet/preview/${encodeURIComponent(btn.dataset.state)}`, { method: "POST" });
    });

    $("btnImportSkin").onclick = () => $("skinImportInput").click();
    $("skinImportInput").onchange = async (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      const form = new FormData();
      form.append("file", file);
      form.append("name", file.name.replace(/\.[^.]+$/, ""));
      try {
        const res = await api("/api/skins/import", { method: "POST", body: form });
        state.skins = await api("/api/skins");
        state.settings = await api("/api/settings");
        renderSkinManager();
        showToast("已切换皮肤：" + res.skin.name);
      } catch (err) {
        showToast("导入失败：" + err.message, 3200);
      }
      e.target.value = "";
    };

    $("btnOpenSkinsDir").onclick = async () => {
      await api("/api/desktop/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "open_skins_dir" }),
      });
    };

    const savePetStyle = async () => {
      $("petScaleVal").textContent = `${$("petScale").value}%`;
      $("petOpacityVal").textContent = `${$("petOpacity").value}%`;
      $("dialogWidthVal").textContent = `${$("dialogWidth").value}px`;
      $("dialogHeightVal").textContent = `${$("dialogHeight").value}px`;
      $("dialogFontSizeVal").textContent = `${$("dialogFontSize").value}px`;
      applyDialogFontSize($("dialogFontSize").value);
      state.settings = await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pet_scale: Number($("petScale").value),
          pet_opacity: Number($("petOpacity").value),
          dialog_width: Number($("dialogWidth").value),
          dialog_max_height: Number($("dialogHeight").value),
          dialog_font_size: Number($("dialogFontSize").value),
          pet_always_on_top: $("petAlwaysOnTop").checked,
          pet_edge_hide: $("petEdgeHide").checked,
          pet_auto_walk: $("petAutoWalk").checked,
          pet_idle_bubbles: $("petIdleBubbles").checked,
          eat_moves_to_recycle_bin: $("eatRecycleBin").checked,
        }),
      });
    };
    $("petScale").oninput = savePetStyle;
    $("petOpacity").oninput = savePetStyle;
    $("dialogWidth").oninput = savePetStyle;
    $("dialogHeight").oninput = savePetStyle;
    $("dialogFontSize").oninput = savePetStyle;
    $("petAlwaysOnTop").onchange = savePetStyle;
    $("petEdgeHide").onchange = savePetStyle;
    $("petAutoWalk").onchange = savePetStyle;
    $("petIdleBubbles").onchange = savePetStyle;
    $("eatRecycleBin").onchange = savePetStyle;

    $("btnSaveMemory").onclick = async () => {
      state.settings = await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          work_memory: $("workMemory").value,
          chat_memory: $("chatMemory").value,
          work_memory_mode: $("workMemoryModeDefault").value,
          chat_memory_mode: $("chatMemoryModeDefault").value,
        }),
      });
      renderMemorySelect();
      showToast("项目与聊天记忆设置已保存");
    };

    $("btnAddPersona").onclick = async () => {
      const name = $("newPersonaName").value.trim();
      const prompt = $("newPersonaPrompt").value.trim();
      if (!name || !prompt) return showToast("请填写名称和提示词");
      await api("/api/personas", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ icon: "", name, prompt }),
      });
      $("newPersonaName").value = "";
      $("newPersonaPrompt").value = "";
      state.personas = await api("/api/personas");
      renderPersonaManager();
      showToast("已添加人设");
    };

    $("btnSaveTiming").onclick = async () => {
      const clamp = (val, lo, hi, def) => {
        const n = Number(val);
        return Number.isFinite(n) ? Math.max(lo, Math.min(hi, Math.round(n))) : def;
      };
      state.settings = await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pet_idle_interval_sec: clamp($("petIdleIntervalSec").value, 5, 120, 10),
          pet_walk_duration_sec: clamp($("petWalkDurationSec").value, 2, 15, 4),
          pet_sleep_timeout_min: clamp($("petSleepTimeoutMin").value, 0, 120, 10),
          pet_bubble_duration_sec: clamp($("petBubbleDurationSec").value, 2, 15, 4),
          care_poll_interval_sec: clamp($("carePollIntervalSec").value, 15, 600, 60),
          ai_timeout_sec: clamp($("aiTimeoutSec").value, 30, 600, 180),
          reminder_enabled: $("reminderEnabled").checked,
          reminder_interval_min: clamp($("reminderIntervalMin").value, 0, 240, 45),
          reminder_daily_time: $("reminderDailyTime").value.trim(),
          reminder_text: $("reminderText").value.trim() || "已经专注一段时间啦，起来活动一下、喝口水吧",
        }),
      });
      renderTimingSettings();
      showToast("时间与轮询设置已生效");
    };

    $("btnSaveSystem").onclick = async () => {
      state.settings = await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          hotkey_toggle: $("hotkeyToggle").value.trim() || "Alt+Space",
          hotkey_screenshot: $("hotkeyScreenshot").value.trim() || "Alt+S",
          launch_at_startup: $("launchAtStartup").checked,
        }),
      });
      showToast("已保存");
    };

    $("btnExportMd").onclick = async () => {
      if (!state.activeConvId) return showToast("当前没有对话");
      const data = await api(`/api/conversations/${state.activeConvId}/export`);
      const blob = new Blob([data.markdown], { type: "text/markdown;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${data.title || "chat"}.md`;
      a.click();
    };

    $("btnClearHistory").onclick = async () => {
      const m = state.historyFilterMode === "chat" ? "chat" : "work";
      const label = m === "chat" ? "聊天记录" : "项目记录";
      if (!confirm(`确定清空全部${label}吗？`)) return;
      await api(`/api/conversations?mode=${m}`, { method: "DELETE" });
      for (const [cid, r] of Object.entries(state.runs)) {
        if (r.mode === m) delete state.runs[cid];
      }
      if (state.activeMode === m) {
        state.activeConvId = null;
        state.viewRunKey = null;
        state.messages = [];
      }
      state.modeConvIds[m] = null;
      state.conversations = await api("/api/conversations");
      renderConversations();
      renderMessages();
      syncComposerButtons();
      showToast(`已清空${label}`);
    };
  }

  window.onDesktopEvent = (name, payload) => {
    if (name === "open_dialog") {
      state.settingsOnlyWindow = false;
      $("settingsModal").classList.add("hidden");
      syncActiveRunsFromServer();
      syncDialogHeight();
      $("chatInput").focus();
    } else if (name === "open_settings") {
      openSettings(payload?.tab || "providers", true);
    } else if (name === "new_chat") {
      $("settingsModal").classList.add("hidden");
      createNewChat();
    } else if (name === "sync_settings" && payload?.settings) {
      state.settings = payload.settings;
      if (state.settings.active_mode) {
        state.activeMode = state.settings.active_mode === "chat" ? "chat" : "work";
      }
      applyDialogFontSize(state.settings.dialog_font_size ?? 11.5);
      renderModeUI();
      renderProjectSelect();
      renderPermissionSelect();
      renderUnifiedModelSelect();
      renderEffortSelect();
      if ($("petAutoWalk")) $("petAutoWalk").checked = state.settings.pet_auto_walk !== false;
      if ($("petAlwaysOnTop")) $("petAlwaysOnTop").checked = !!state.settings.pet_always_on_top;
    } else if (name === "project_selected" && payload?.settings) {
      state.settings = payload.settings;
      state.activeMode = "work";
      state.activeConvId = null;
      state.viewRunKey = null;
      state.modeConvIds.work = null;
      state.messages = [];
      renderModeUI();
      renderProjectSelect();
      renderMessages();
      syncComposerButtons();
      const p = state.settings.active_project_dir || "";
      if (p) showToast(`已选择项目：${p.split(/[\\/]/).filter(Boolean).pop()}`);
    } else if (name === "add_attachment" && payload?.attachment) {
      state.pendingAttachments.push(payload.attachment);
      renderAttachmentsBar();
      $("settingsModal").classList.add("hidden");
      if (payload.focus_input) $("chatInput").focus();
    } else if (name === "quick_send" && payload?.content) {
      $("settingsModal").classList.add("hidden");
      sendMessage(payload.content);
    } else if (name === "inspect_and_explain" && payload?.attachments) {
      $("settingsModal").classList.add("hidden");
      // 拖入新文件要求读取时，自动开启独立干净的新会话，避免 Kimi 沿用旧对话记忆串台或胡说
      state.activeConvId = null;
      state.viewRunKey = null;
      state.modeConvIds[state.activeMode] = null;
      state.messages = [];
      state.pendingAttachments = [...payload.attachments];
      renderAttachmentsBar();
      sendMessage(payload.prompt || "请告诉我这些文件分别是什么并概括主要内容。");
    } else if (name === "local_file_report" && payload?.report) {
      $("settingsModal").classList.add("hidden");
      state.messages.push({
        id: "local_u_" + Date.now(),
        role: "user",
        content: payload.attachments?.length > 1 ? `读取 ${payload.attachments.length} 个文件` : "读取文件",
        attachments: payload.attachments || [],
      });
      state.messages.push({
        id: "local_a_" + Date.now(),
        role: "assistant",
        content: payload.report,
        reasoning: "",
        sources: [],
        model: "本地解析",
      });
      renderMessages();
    } else if (name === "trigger_upload") {
      $("settingsModal").classList.add("hidden");
      $("fileInput").click();
    }
  };

  bindEvents();
  bootstrap().catch((err) => showToast("初始化失败：" + err.message, 3500));
})();

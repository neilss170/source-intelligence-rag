import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  Calculator,
  Columns2,
  FileText,
  Layers3,
  LogOut,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Paperclip,
  Pencil,
  Plus,
  Sparkles,
  Square,
  Trash2,
  Upload,
} from "lucide-react";
import { api } from "./api";
import { Answer, fromServer } from "./Answer";
import { AuthScreen } from "./AuthScreen";

const suggestions = [
  { icon: FileText, text: "Summarise my uploaded documents" },
  { icon: Calculator, text: "Total and average a column in my spreadsheet" },
  { icon: Columns2, text: "Compare the key figures across my files" },
  { icon: Sparkles, text: "What can you do with my documents?" },
];
const PENDING = new Set(["uploaded", "indexing"]);

function greeting() {
  const hour = new Date().getHours();
  if (hour >= 5 && hour < 12) return "Good morning";
  if (hour >= 12 && hour < 17) return "Good afternoon";
  return "Good evening";
}

function Backdrop() {
  return (
    <div className="backdrop" aria-hidden="true">
      <span className="glow" />
      <span className="streak streak-one" />
      <span className="streak streak-two" />
      <span className="streak streak-three" />
    </div>
  );
}

export default function App() {
  // undefined while checking the session, null when signed out.
  const [session, setSession] = useState(undefined);

  useEffect(() => {
    api.me().then(setSession).catch(() => setSession(null));
  }, []);

  if (session === undefined) {
    return <div className="app-shell"><Backdrop /></div>;
  }
  if (!session) {
    return (
      <div className="app-shell">
        <Backdrop />
        <AuthScreen onSignedIn={setSession} />
      </div>
    );
  }
  return <Workspace session={session} onSignedOut={() => setSession(null)} />;
}

function Workspace({ session, onSignedOut }) {
  const [sidebarOpen, setSidebarOpen] = useState(
    () => window.matchMedia("(min-width: 900px)").matches,
  );
  const [chats, setChats] = useState([]);
  const [activeChatId, setActiveChatId] = useState(null);
  const [messages, setMessages] = useState({});
  const [documents, setDocuments] = useState([]);
  const [uploadProgress, setUploadProgress] = useState(null);
  const [deletingId, setDeletingId] = useState("");
  const [scope, setScope] = useState("auto");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef(null);
  const fileInput = useRef(null);
  const scrollArea = useRef(null);
  const firstName = (session.user.name || "").split(" ")[0] || "there";
  const thread = activeChatId ? messages[activeChatId] || [] : [];

  // Any failure that means "your session ended" sends you back to sign in.
  const handle = useCallback(
    (failure) => {
      if (failure?.status === 401) onSignedOut();
      else if (failure?.name !== "AbortError") setError(failure.message);
    },
    [onSignedOut],
  );

  const refreshChats = useCallback(
    () => api.listChats().then(setChats).catch(handle),
    [handle],
  );

  useEffect(() => {
    refreshChats();
    api.listDocuments().then(setDocuments).catch(handle);
  }, [refreshChats, handle]);

  // Poll while anything is still indexing.
  const anyPending = documents.some((d) => PENDING.has(d.status));
  useEffect(() => {
    if (!anyPending) return undefined;
    const timer = setInterval(() => {
      api.listDocuments().then(setDocuments).catch(handle);
    }, 2000);
    return () => clearInterval(timer);
  }, [anyPending, handle]);

  useEffect(() => {
    scrollArea.current?.scrollTo({ top: scrollArea.current.scrollHeight, behavior: "smooth" });
  }, [thread.length, thread[thread.length - 1]?.content, activeChatId]);

  async function openChat(chatId) {
    setActiveChatId(chatId);
    setError("");
    if (window.matchMedia("(max-width: 899px)").matches) setSidebarOpen(false);
    if (!messages[chatId]) {
      try {
        const stored = await api.listMessages(chatId);
        setMessages((all) => ({ ...all, [chatId]: stored.map(fromServer) }));
      } catch (failure) {
        handle(failure);
      }
    }
  }

  function newChat() {
    // The chat is created on the server with its first question.
    setActiveChatId(null);
    setQuery("");
    setError("");
  }

  async function renameChat(chat) {
    const title = window.prompt("Rename chat", chat.title)?.trim();
    if (!title) return;
    try {
      const renamed = await api.renameChat(chat.id, title);
      setChats((all) => all.map((c) => (c.id === chat.id ? renamed : c)));
    } catch (failure) {
      handle(failure);
    }
  }

  async function deleteChat(chat) {
    if (!window.confirm(`Delete "${chat.title}"?`)) return;
    try {
      await api.deleteChat(chat.id);
      setChats((all) => all.filter((c) => c.id !== chat.id));
      if (activeChatId === chat.id) setActiveChatId(null);
    } catch (failure) {
      handle(failure);
    }
  }

  async function ask(text) {
    const question = text.trim();
    if (!question || streaming) return;
    setError("");
    setQuery("");

    let chatId = activeChatId;
    if (!chatId) {
      try {
        const chat = await api.createChat();
        chatId = chat.id;
        setChats((all) => [chat, ...all]);
        setMessages((all) => ({ ...all, [chatId]: [] }));
        setActiveChatId(chatId);
      } catch (failure) {
        setQuery(question);
        handle(failure);
        return;
      }
    }

    const answerId = `pending-${Date.now()}`;
    setMessages((all) => ({
      ...all,
      [chatId]: [
        ...(all[chatId] || []),
        { id: `${answerId}-q`, role: "user", content: question },
        { id: answerId, role: "assistant", content: "", streaming: true, question },
      ],
    }));
    const patch = (change) =>
      setMessages((all) => ({
        ...all,
        [chatId]: (all[chatId] || []).map((m) =>
          m.id === answerId ? { ...m, ...(typeof change === "function" ? change(m) : change) } : m,
        ),
      }));

    const controller = new AbortController();
    abortRef.current = controller;
    setStreaming(true);
    let finished = false;
    try {
      await api.ask(chatId, question, scope, {
        signal: controller.signal,
        onEvent(name, data) {
          if (name === "status") patch({ status: data.text });
          else if (name === "token") patch((m) => ({ content: m.content + data.text }));
          else if (name === "citations") patch({ citations: data.citations });
          else if (name === "web_sources") patch({ webSources: data.sources });
          else if (name === "verification") patch({ unsupported: data.unsupported_claims });
          else if (name === "done") {
            finished = true;
            patch({ id: data.message_id, content: data.content, mode: data.mode, streaming: false });
          } else if (name === "error") {
            finished = true;
            patch({ error: data, streaming: false });
          }
        },
      });
      if (!finished) {
        patch({ streaming: false, error: { code: "interrupted", message: "The answer was interrupted." } });
      }
    } catch (failure) {
      if (failure.name === "AbortError") patch({ streaming: false, stopped: true });
      else {
        patch({ streaming: false, error: { code: failure.code, message: failure.message } });
        if (failure.status === 401) onSignedOut();
      }
    } finally {
      abortRef.current = null;
      setStreaming(false);
      refreshChats();
    }
  }

  function retry(message) {
    setMessages((all) => ({
      ...all,
      [activeChatId]: (all[activeChatId] || []).filter(
        (m) => m.id !== message.id && m.id !== `${message.id}-q`,
      ),
    }));
    ask(message.question);
  }

  async function upload(event) {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length) return;
    setError("");
    setUploadProgress(0);
    try {
      const accepted = await api.uploadDocuments(files, setUploadProgress);
      setDocuments((all) => [
        ...accepted.filter((doc) => !all.some((d) => d.id === doc.id)),
        ...all,
      ]);
    } catch (failure) {
      handle(failure);
    } finally {
      setUploadProgress(null);
    }
  }

  async function removeDocument(doc) {
    setDeletingId(doc.id);
    try {
      await api.deleteDocument(doc.id);
      setDocuments((all) => all.filter((d) => d.id !== doc.id));
    } catch (failure) {
      handle(failure);
    } finally {
      setDeletingId("");
    }
  }

  async function signOut() {
    abortRef.current?.abort();
    try {
      await api.logOut();
    } catch {
      // Signed out either way.
    }
    onSignedOut();
  }

  const readyCount = documents.filter((d) => d.status === "ready").length;
  const indexingCount = documents.filter((d) => PENDING.has(d.status)).length;
  const showGreeting = thread.length === 0;

  return (
    <div className={`app-shell ${sidebarOpen ? "sidebar-visible" : ""}`}>
      <Backdrop />
      {sidebarOpen && (
        <button className="scrim" type="button" aria-label="Close sidebar" onClick={() => setSidebarOpen(false)} />
      )}

      <aside className={`chat-sidebar ${sidebarOpen ? "open" : ""}`} aria-label="Chats and documents">
        <div className="sidebar-header">
          <span className="brand-mark"><Layers3 size={15} /></span>
          <strong>Chats</strong>
          <button className="ghost-icon" type="button" onClick={() => setSidebarOpen(false)} aria-label="Close sidebar">
            <PanelLeftClose size={17} />
          </button>
        </div>
        <button className="new-chat" type="button" onClick={newChat}>
          <Plus size={16} /> New chat
        </button>
        <nav className="chat-list" aria-label="Chats">
          {chats.length === 0 && <p className="sidebar-note">Your chats will appear here.</p>}
          {chats.map((chat) => (
            <div className={`chat-row ${chat.id === activeChatId ? "active" : ""}`} key={chat.id}>
              <button
                className="chat-select"
                type="button"
                onClick={() => openChat(chat.id)}
                aria-current={chat.id === activeChatId ? "page" : undefined}
              >
                <MessageSquare size={14} />
                <span>{chat.title}</span>
              </button>
              <div className="chat-actions">
                <button type="button" onClick={() => renameChat(chat)} aria-label={`Rename ${chat.title}`}><Pencil size={12} /></button>
                <button type="button" onClick={() => deleteChat(chat)} aria-label={`Delete ${chat.title}`}><Trash2 size={12} /></button>
              </div>
            </div>
          ))}
        </nav>

        <div className="sidebar-section">
          <span className="sidebar-label">Documents</span>
          {documents.length === 0 && <p className="sidebar-note">Nothing uploaded yet.</p>}
          <ul className="document-list" aria-label="Your documents">
            {documents.map((doc) => (
              <li className={`document-chip ${doc.status}`} key={doc.id}>
                <FileText size={12} />
                <span className="document-name" title={doc.filename}>{doc.filename}</span>
                {PENDING.has(doc.status) && <span className="doc-badge">Indexing…</span>}
                {doc.status === "failed" && <span className="doc-badge failed" title={doc.error}>Failed</span>}
                <button
                  type="button"
                  className="remove-document"
                  aria-label={`Delete ${doc.filename}`}
                  disabled={deletingId === doc.id}
                  onClick={() => removeDocument(doc)}
                >
                  <Trash2 size={12} />
                </button>
                {doc.status === "failed" && doc.error && <span className="doc-error">{doc.error}</span>}
              </li>
            ))}
          </ul>
        </div>

        <div className="sidebar-section">
          <span className="sidebar-label">Answer from</span>
          <div className="scope-switcher" role="radiogroup" aria-label="Answer from">
            {[["auto", "Auto"], ["workspace", "Documents"], ["general", "General"]].map(([value, label]) => (
              <button
                className={scope === value ? "active" : ""}
                key={value}
                type="button"
                role="radio"
                aria-checked={scope === value}
                onClick={() => setScope(value)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="sidebar-account">
          <span className="avatar small" aria-hidden="true">{firstName.slice(0, 1).toUpperCase()}</span>
          <span className="account-email" title={session.user.email}>{session.user.email}</span>
          <button className="ghost-icon" type="button" onClick={signOut} aria-label="Sign out">
            <LogOut size={15} />
          </button>
        </div>
      </aside>

      <div className="page-column">
        <header className="topbar">
          <div className="brand-wrap">
            {!sidebarOpen && (
              <button className="glass-icon" type="button" onClick={() => setSidebarOpen(true)} aria-label="Open sidebar">
                <PanelLeftOpen size={18} />
              </button>
            )}
            <span className="brand">Source Intelligence</span>
          </div>
          <div className="top-actions">
            <span className="doc-pill">
              <span className={`status-dot ${readyCount ? "ready" : ""}`} />
              {indexingCount
                ? `Indexing ${indexingCount}…`
                : readyCount
                  ? `${readyCount} ${readyCount === 1 ? "document" : "documents"}`
                  : "No documents"}
            </span>
            <button className="glass-button" type="button" disabled={uploadProgress !== null} onClick={() => fileInput.current?.click()}>
              <Upload size={15} />
              <span className="hide-small">
                {uploadProgress !== null ? `Uploading ${Math.round(uploadProgress * 100)}%` : "Upload"}
              </span>
            </button>
            <input ref={fileInput} className="sr-only" type="file" accept=".pdf,.docx,.txt,.md,.markdown,.csv,.json,.xlsx" multiple onChange={upload} />
          </div>
          {uploadProgress !== null && (
            <div className="upload-bar" role="progressbar" aria-label="Upload progress" aria-valuenow={Math.round(uploadProgress * 100)} aria-valuemin={0} aria-valuemax={100}>
              <span style={{ width: `${Math.round(uploadProgress * 100)}%` }} />
            </div>
          )}
        </header>

        <main className="conversation" ref={scrollArea}>
          {showGreeting ? (
            <section className="greeting">
              <span className="avatar" aria-hidden="true">{firstName.slice(0, 1).toUpperCase()}</span>
              <h1>{greeting()},<br />{firstName}</h1>
              <p>Ask about your documents, or ask anything.</p>
            </section>
          ) : (
            <div className="thread" aria-live="polite">
              {thread.map((message) =>
                message.role === "user" ? (
                  <div className="question" key={message.id}>{message.content}</div>
                ) : (
                  <Answer
                    key={message.id}
                    message={message}
                    onRetry={message.error && message.question ? () => retry(message) : undefined}
                  />
                ),
              )}
            </div>
          )}
        </main>

        <div className="dock">
          {error && (
            <div className="error-message" role="alert">
              {error}
              <button type="button" onClick={() => setError("")} aria-label="Dismiss">×</button>
            </div>
          )}

          {showGreeting && !streaming && (
            <div className="suggestion-row">
              {suggestions.map(({ icon: Icon, text }) => (
                <button className="suggestion-card" key={text} type="button" onClick={() => ask(text)}>
                  <span className="suggestion-icon"><Icon size={14} /></span>
                  <span>{text}</span>
                </button>
              ))}
            </div>
          )}

          <form className="prompt-bar" onSubmit={(event) => { event.preventDefault(); ask(query); }}>
            <button className="attach-button" type="button" aria-label="Upload documents" disabled={uploadProgress !== null} onClick={() => fileInput.current?.click()}>
              <Paperclip size={17} />
            </button>
            <textarea
              aria-label="Ask a question"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  ask(query);
                }
              }}
              placeholder="Ask about your documents"
              rows={1}
              maxLength={4000}
            />
            {streaming ? (
              <button className="send-button stop" type="button" aria-label="Stop answering" onClick={() => abortRef.current?.abort()}>
                <Square size={14} fill="currentColor" />
              </button>
            ) : (
              <button className="send-button" type="submit" aria-label="Send" disabled={!query.trim()}>
                <ArrowUp size={18} />
              </button>
            )}
          </form>
        </div>
      </div>
    </div>
  );
}

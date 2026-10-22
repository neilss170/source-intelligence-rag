import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUp,
  Check,
  ChevronDown,
  Copy,
  Calculator,
  Columns2,
  FileText,
  Layers3,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Paperclip,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import {
  askAssistant,
  deleteDocument,
  listDocuments,
  uploadDocuments,
} from "./api";

const STORAGE_KEY = "source-intelligence-chats-v1";
const USER_NAME = "Neil";
const suggestions = [
  { icon: FileText, text: "Summarise my uploaded documents" },
  { icon: Calculator, text: "Total and average a column in my spreadsheet" },
  { icon: Columns2, text: "Compare the key figures across my files" },
  { icon: Sparkles, text: "What can you do with my documents?" },
];

function greeting() {
  const hour = new Date().getHours();
  if (hour >= 5 && hour < 12) return "Good morning";
  if (hour >= 12 && hour < 17) return "Good afternoon";
  return "Good evening";
}

// Answer text marks its sources as [1], [2]; show them as small numbered
// badges that match the citation list below the answer.
function withCitationMarks(text) {
  return text.split(/(\[\d+\])/g).map((part, index) => {
    const match = /^\[(\d+)\]$/.exec(part);
    return match ? <sup className="cite-mark" key={index}>{match[1]}</sup> : part;
  });
}

function Answer({ answer }) {
  const [showSources, setShowSources] = useState(false);
  const [copied, setCopied] = useState(false);
  const sources = [
    ...answer.citations.map((citation, index) => ({
      key: citation.evidence_id,
      number: index + 1,
      title: citation.title.split(" > ").slice(-1)[0],
      file: citation.title.split(" > ")[0],
      page: citation.page,
      excerpt: citation.excerpt,
    })),
    ...(answer.webSources || []).map((source, index) => ({
      key: source.url,
      number: answer.citations.length + index + 1,
      title: source.title,
      url: source.url,
      excerpt: source.excerpt,
    })),
  ];
  const unverified = answer.unsupportedClaims || [];

  async function copy() {
    try {
      await navigator.clipboard.writeText(answer.body.replace(/\[\d+\]/g, ""));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard can be blocked; nothing to undo.
    }
  }

  return (
    <article className="answer">
      <div className="answer-copy">
        {answer.body.split("\n\n").map((paragraph, index) => <p key={index}>{withCitationMarks(paragraph)}</p>)}
      </div>

      <div className="answer-meta">
        {sources.length > 0 && (
          <button className="meta-button" type="button" aria-expanded={showSources} onClick={() => setShowSources((open) => !open)}>
            {sources.length} {sources.length === 1 ? "source" : "sources"}
            <ChevronDown size={13} className={showSources ? "flipped" : ""} />
          </button>
        )}
        {answer.mode === "general" && <span className="meta-note">Not from your documents</span>}
        {unverified.length > 0 && (
          <span className="meta-note warn" title={unverified.join("\n")}>
            {unverified.length === 1 ? "1 line unverified" : `${unverified.length} lines unverified`}
          </span>
        )}
        <button className="meta-icon" type="button" onClick={copy} aria-label="Copy answer">
          {copied ? <Check size={13} /> : <Copy size={13} />}
        </button>
      </div>

      {showSources && (
        <ol className="sources">
          {sources.map((source) => (
            <li key={source.key}>
              <span className="source-number">{source.number}</span>
              <div>
                {source.url ? (
                  <a href={source.url} target="_blank" rel="noreferrer">{source.title}</a>
                ) : (
                  <strong>{source.title}</strong>
                )}
                {source.file && <span className="source-file">{source.file}{source.page ? ` · p. ${source.page}` : ""}</span>}
                {source.excerpt && <p>{source.excerpt}</p>}
              </div>
            </li>
          ))}
          {unverified.length > 0 && (
            <li className="unverified">
              <span className="source-number">!</span>
              <div>
                <strong>Not clearly supported by the sources</strong>
                {unverified.map((claim) => <p key={claim}>{claim}</p>)}
              </div>
            </li>
          )}
        </ol>
      )}
    </article>
  );
}

function makeChat() {
  return {
    id: crypto.randomUUID(),
    title: "New chat",
    createdAt: Date.now(),
    updatedAt: Date.now(),
    answers: [],
  };
}

function loadChats() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    return Array.isArray(saved) && saved.length ? saved : [makeChat()];
  } catch {
    return [makeChat()];
  }
}

function historyFromAnswers(answers) {
  return answers.slice(-6).flatMap((answer) => [
    { role: "user", content: answer.question },
    { role: "assistant", content: answer.body },
  ]);
}

function App() {
  const initialChats = useMemo(loadChats, []);
  const [chats, setChats] = useState(initialChats);
  const [activeChatId, setActiveChatId] = useState(initialChats[0].id);
  const [sidebarOpen, setSidebarOpen] = useState(
    () => window.matchMedia("(min-width: 900px)").matches,
  );
  const [query, setQuery] = useState("");
  const [pendingQuestion, setPendingQuestion] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [deletingDocumentId, setDeletingDocumentId] = useState("");
  const [documents, setDocuments] = useState([]);
  const [scope, setScope] = useState("auto");
  const fileInput = useRef(null);
  const scrollArea = useRef(null);

  const activeChat = chats.find((chat) => chat.id === activeChatId) || chats[0];
  const answers = activeChat?.answers || [];

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(chats));
    } catch {
      // Storage can be full or blocked; chats still work for this session.
    }
  }, [chats]);

  useEffect(() => {
    scrollArea.current?.scrollTo({ top: scrollArea.current.scrollHeight, behavior: "smooth" });
  }, [answers.length, isGenerating, activeChatId]);

  useEffect(() => {
    listDocuments()
      .then(setDocuments)
      .catch(() => setError("Indexed documents could not be loaded."));
  }, []);

  function createChat() {
    const chat = makeChat();
    setChats((current) => [chat, ...current]);
    setActiveChatId(chat.id);
    setQuery("");
    setError("");
  }

  function removeChat(chatId) {
    setChats((current) => {
      const remaining = current.filter((chat) => chat.id !== chatId);
      const next = remaining.length ? remaining : [makeChat()];
      if (chatId === activeChatId) setActiveChatId(next[0].id);
      return next;
    });
  }

  function renameChat(chat) {
    const title = window.prompt("Rename chat", chat.title)?.trim();
    if (!title) return;
    setChats((current) =>
      current.map((item) => item.id === chat.id ? { ...item, title } : item),
    );
  }

  async function handleUpload(event) {
    const selected = Array.from(event.target.files || []);
    event.target.value = "";
    if (!selected.length) return;
    setIsUploading(true);
    setError("");
    try {
      const results = await uploadDocuments(selected);
      setDocuments((current) => [
        ...current,
        ...results.filter(
          (result) => !current.some((item) => item.document_id === result.document_id),
        ),
      ]);
    } catch (uploadError) {
      setError(uploadError.message);
    } finally {
      setIsUploading(false);
    }
  }

  function submit(event) {
    event.preventDefault();
    ask(query);
  }

  async function ask(text) {
    const prompt = text.trim();
    if (!prompt || isGenerating || !activeChat) return;
    setPendingQuestion(prompt);
    setQuery("");
    setIsGenerating(true);
    setError("");
    try {
      const result = await askAssistant(
        prompt,
        scope,
        historyFromAnswers(activeChat.answers),
        activeChat.id,
      );
      const answer = {
        id: crypto.randomUUID(),
        question: prompt,
        body: result.answer,
        citations: result.citations,
        webSources: result.web_sources || [],
        grounded: result.grounded,
        unsupportedClaims: result.unsupported_claims || [],
        queryType: result.query_type,
        mode: result.mode,
        createdAt: Date.now(),
      };
      setChats((current) => current.map((chat) => {
        if (chat.id !== activeChat.id) return chat;
        return {
          ...chat,
          title: chat.answers.length === 0 ? prompt.slice(0, 42) : chat.title,
          answers: [...chat.answers, answer],
          updatedAt: Date.now(),
        };
      }));
    } catch {
      setQuery(prompt);
      setError("The assistant is unavailable. Make sure the API is running and try again.");
    } finally {
      setIsGenerating(false);
    }
  }

  async function handleDelete(document) {
    setDeletingDocumentId(document.document_id);
    setError("");
    try {
      await deleteDocument(document.document_id);
      setDocuments((current) =>
        current.filter((item) => item.document_id !== document.document_id),
      );
    } catch (deleteError) {
      setError(deleteError.message);
    } finally {
      setDeletingDocumentId("");
    }
  }

  const showGreeting = answers.length === 0 && !isGenerating;

  return (
    <div className={`app-shell ${sidebarOpen ? "sidebar-visible" : ""}`}>
      <div className="backdrop" aria-hidden="true">
        <span className="glow" />
        <span className="streak streak-one" />
        <span className="streak streak-two" />
        <span className="streak streak-three" />
      </div>

      {sidebarOpen && (
        <button className="scrim" type="button" aria-label="Close chat history" onClick={() => setSidebarOpen(false)} />
      )}

      <aside className={`chat-sidebar ${sidebarOpen ? "open" : ""}`}>
        <div className="sidebar-header">
          <span className="brand-mark"><Layers3 size={15} /></span>
          <strong>Chats</strong>
          <button className="ghost-icon" type="button" onClick={() => setSidebarOpen(false)} aria-label="Close chat history">
            <PanelLeftClose size={17} />
          </button>
        </div>
        <button className="new-chat" type="button" onClick={createChat}>
          <Plus size={16} /> New chat
        </button>
        <div className="chat-list">
          {[...chats].sort((a, b) => b.updatedAt - a.updatedAt).map((chat) => (
            <div className={`chat-row ${chat.id === activeChatId ? "active" : ""}`} key={chat.id}>
              <button className="chat-select" type="button" onClick={() => setActiveChatId(chat.id)}>
                <MessageSquare size={14} />
                <span>{chat.title}</span>
              </button>
              <div className="chat-actions">
                <button type="button" onClick={() => renameChat(chat)} aria-label={`Rename ${chat.title}`}><Pencil size={12} /></button>
                <button type="button" onClick={() => removeChat(chat.id)} aria-label={`Delete ${chat.title}`}><Trash2 size={12} /></button>
              </div>
            </div>
          ))}
        </div>

        <div className="sidebar-section">
          <span className="sidebar-label">Documents</span>
          {documents.length === 0 && <p className="sidebar-note">Nothing uploaded yet.</p>}
          <div className="document-list" aria-label="Indexed documents">
            {documents.map((document) => (
              <span className="document-chip" key={document.document_id}>
                <FileText size={12} />
                <span className="document-name">{document.filename}</span>
                <button type="button" className="remove-document" aria-label={`Remove ${document.filename}`} disabled={deletingDocumentId === document.document_id} onClick={() => handleDelete(document)}>
                  <Trash2 size={12} />
                </button>
              </span>
            ))}
          </div>
        </div>
        <div className="sidebar-section">
          <span className="sidebar-label">Answer from</span>
          <div className="scope-switcher" aria-label="Answer source">
            {[["auto", "Auto"], ["workspace", "Documents"], ["general", "General"]].map(([value, label]) => (
              <button className={scope === value ? "active" : ""} key={value} type="button" onClick={() => setScope(value)}>{label}</button>
            ))}
          </div>
        </div>
        <p className="sidebar-note">Chats are saved privately in this browser.</p>
      </aside>

      <div className="page-column">
        <header className="topbar">
          <div className="brand-wrap">
            {!sidebarOpen && (
              <button className="glass-icon" type="button" onClick={() => setSidebarOpen(true)} aria-label="Open chat history">
                <PanelLeftOpen size={18} />
              </button>
            )}
            <span className="brand">Source Intelligence</span>
          </div>
          <div className="top-actions">
            <span className="doc-pill">
              <span className={`status-dot ${documents.length ? "ready" : ""}`} />
              {documents.length ? `${documents.length} ${documents.length === 1 ? "document" : "documents"}` : "No documents"}
            </span>
            <button className="glass-button" type="button" disabled={isUploading} onClick={() => fileInput.current?.click()}>
              <Upload size={15} /> <span className="hide-small">{isUploading ? "Indexing..." : "Upload"}</span>
            </button>
            <input ref={fileInput} className="sr-only" type="file" accept=".pdf,.docx,.txt,.md,.markdown,.csv,.json,.xlsx" multiple onChange={handleUpload} />
          </div>
        </header>

        <main className="conversation" ref={scrollArea}>
          {showGreeting ? (
            <section className="greeting">
              <span className="avatar" aria-hidden="true">{USER_NAME.slice(0, 1)}</span>
              <h1>{greeting()},<br />{USER_NAME}</h1>
              <p>Ask about your documents, or ask anything.</p>
            </section>
          ) : (
            <div className="thread" aria-live="polite">
              {answers.map((answer) => (
                <div className="turn" key={answer.id}>
                  <div className="question">{answer.question}</div>
                  <Answer answer={answer} />
                </div>
              ))}
              {isGenerating && (
                <div className="turn">
                  <div className="question">{pendingQuestion}</div>
                  <div className="thinking" role="status" aria-label="Thinking"><span /><span /><span /></div>
                </div>
              )}
            </div>
          )}
        </main>

        <div className="dock">
          {error && <div className="error-message" role="alert">{error}</div>}

          {showGreeting && (
            <div className="suggestion-row">
              {suggestions.map(({ icon: Icon, text }) => (
                <button className="suggestion-card" key={text} type="button" onClick={() => ask(text)}>
                  <span className="suggestion-icon"><Icon size={14} /></span>
                  <span>{text}</span>
                </button>
              ))}
            </div>
          )}

          <form className="prompt-bar" onSubmit={submit}>
            <button className="attach-button" type="button" aria-label="Upload documents" disabled={isUploading} onClick={() => fileInput.current?.click()}>
              <Paperclip size={17} />
            </button>
            <textarea
              aria-label="Ask a question"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(event); }
              }}
              placeholder="Ask about your documents"
              rows={1}
            />
            <button className="send-button" type="submit" aria-label="Send" disabled={!query.trim() || isGenerating}>
              <ArrowUp size={18} />
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

export default App;

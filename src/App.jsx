import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUp,
  FileText,
  Layers3,
  Menu,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Plus,
  Search,
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
const suggestions = [
  "Summarize the uploaded documents",
  "What programming languages are listed?",
  "Explain retrieval-augmented generation simply",
];
const modeLabels = {
  workspace: "Document-grounded answer",
  general: "General assistant",
  empty_workspace: "Documents required",
  ambiguous: "Clarification needed",
  unsupported_analysis: "Analysis unavailable",
};

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
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [query, setQuery] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [deletingDocumentId, setDeletingDocumentId] = useState("");
  const [documents, setDocuments] = useState([]);
  const [scope, setScope] = useState("auto");
  const fileInput = useRef(null);

  const activeChat = chats.find((chat) => chat.id === activeChatId) || chats[0];
  const answers = activeChat?.answers || [];

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(chats));
  }, [chats]);

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

  async function submit(event) {
    event.preventDefault();
    const prompt = query.trim();
    if (!prompt || isGenerating || !activeChat) return;
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
      setQuery("");
    } catch {
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

  return (
    <div className={`app-shell ${sidebarOpen ? "sidebar-visible" : ""}`}>
      <aside className={`chat-sidebar ${sidebarOpen ? "open" : ""}`}>
        <div className="sidebar-header">
          <span className="brand-mark"><Layers3 size={16} /></span>
          <strong>Chats</strong>
          <button className="sidebar-icon" onClick={() => setSidebarOpen(false)} aria-label="Close chat history">
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
        <p className="sidebar-note">Chats are saved privately in this browser.</p>
      </aside>

      <div className="page-column">
        <header className="topbar">
          <div className="brand-wrap">
            {!sidebarOpen && (
              <button className="icon-button" onClick={() => setSidebarOpen(true)} aria-label="Open chat history">
                <PanelLeftOpen size={18} />
              </button>
            )}
            <a className="brand" href="#" aria-label="Source home">
              <span className="brand-mark"><Layers3 size={16} /></span>
              <span>source intelligence</span>
            </a>
          </div>
          <div className="top-actions">
            <span className="status"><span className="status-dot" />Hybrid assistant</span>
            <button className="icon-button" aria-label="Open menu"><Menu size={18} /></button>
          </div>
        </header>

        <main>
          {answers.length === 0 && (
            <section className="hero">
              <div className="eyebrow"><Sparkles size={13} /> Chat + grounded intelligence</div>
              <h1>Ask your data.<br />Or ask anything.</h1>
              <p>Chat naturally, use uploaded documents for cited answers, and keep every conversation organized.</p>
            </section>
          )}

          <section className="workspace" aria-label="Chat workspace">
            <div className="source-row">
              <div className="source-state">
                <span className="source-icon"><FileText size={17} /></span>
                <div>
                  <strong>{documents.length ? `${documents.length} ${documents.length === 1 ? "document" : "documents"} ready` : "No documents uploaded"}</strong>
                  <span>PDF, DOCX, TXT, Markdown, CSV, JSON, or Excel</span>
                </div>
              </div>
              <div className="source-actions">
                <span className="grounded-badge">Auto routing</span>
                <button className="add-source" type="button" disabled={isUploading} onClick={() => fileInput.current?.click()}>
                  <Upload size={15} /> {isUploading ? "Indexing..." : "Upload"}
                </button>
                <input ref={fileInput} className="sr-only" type="file" accept=".pdf,.docx,.txt,.md,.markdown,.csv,.json,.xlsx" multiple onChange={handleUpload} />
              </div>
            </div>

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

            <div className="answer-history" aria-live="polite">
              {answers.map((answer) => (
                <article className="answer-card" key={answer.id}>
                  <div className="answer-header">
                    <span className="answer-label">{modeLabels[answer.mode] || "Assistant answer"}</span>
                    <span className="answer-type">{answer.queryType}</span>
                  </div>
                  <h2>{answer.question}</h2>
                  <div className="answer-copy">
                    {answer.body.split("\n\n").map((paragraph, index) => <p key={`${answer.id}-${index}`}>{paragraph}</p>)}
                  </div>
                  {answer.citations.length > 0 && (
                    <div className="citation-list">
                      {answer.citations.map((citation) => (
                        <details className="citation" key={citation.evidence_id}>
                          <summary><FileText size={14} />{citation.title} · p. {citation.page}</summary>
                          <p>{citation.excerpt}</p>
                        </details>
                      ))}
                    </div>
                  )}
                  {answer.webSources?.length > 0 && (
                    <div className="web-source-list">
                      {answer.webSources.map((source) => (
                        <a href={source.url} target="_blank" rel="noreferrer" key={source.url}>
                          <strong>{source.title}</strong>
                          {source.excerpt && <span>{source.excerpt}</span>}
                        </a>
                      ))}
                    </div>
                  )}
                </article>
              ))}
            </div>

            {isGenerating && <div className="answer-card loading" aria-live="polite"><span /><span /><span /></div>}
            {error && <div className="error-message" role="alert">{error}</div>}

            <form className="prompt-box" onSubmit={submit}>
              <div className="scope-switcher" aria-label="Answer source">
                {[["auto", "Auto"], ["workspace", "Documents"], ["general", "General"]].map(([value, label]) => (
                  <button className={scope === value ? "active" : ""} key={value} type="button" onClick={() => setScope(value)}>{label}</button>
                ))}
              </div>
              <textarea aria-label="Ask a question" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(event); }
              }} placeholder="Message Source Intelligence..." rows={3} />
              <div className="prompt-footer">
                <span className="prompt-hint">Enter to send · Shift + Enter for a new line</span>
                <button className="generate-button" type="submit" disabled={!query.trim() || isGenerating}>
                  <span>{isGenerating ? "Thinking" : "Send"}</span><ArrowUp size={16} />
                </button>
              </div>
            </form>

            {answers.length === 0 && !isGenerating && (
              <div className="suggestions">
                {suggestions.map((suggestion) => <button key={suggestion} onClick={() => setQuery(suggestion)}><Search size={13} /> {suggestion}</button>)}
              </div>
            )}
          </section>
        </main>

        <footer><span>Private by design</span><span>Hybrid RAG chatbot · 2026</span></footer>
      </div>
    </div>
  );
}

export default App;

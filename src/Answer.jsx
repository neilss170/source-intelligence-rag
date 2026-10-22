import { useState } from "react";
import { Check, ChevronDown, Copy, RotateCcw } from "lucide-react";

// Answer text marks its sources as [1], [2]; show them as small numbers that
// match the source list below the answer.
function withCitationMarks(text) {
  return text.split(/(\[\d+\])/g).map((part, index) => {
    const match = /^\[(\d+)\]$/.exec(part);
    return match ? <sup className="cite-mark" key={index}>{match[1]}</sup> : part;
  });
}

export function Answer({ message, onRetry }) {
  const [showSources, setShowSources] = useState(false);
  const [copied, setCopied] = useState(false);
  const citations = message.citations || [];
  const sources = [
    ...citations.map((citation) => ({
      key: citation.evidence_id || citation.number,
      number: citation.number,
      title: citation.title.split(" > ").slice(-1)[0],
      file: citation.filename,
      page: citation.page,
      excerpt: citation.excerpt,
    })),
    ...(message.webSources || []).map((source, index) => ({
      key: source.url,
      number: citations.length + index + 1,
      title: source.title,
      url: source.url,
      excerpt: source.excerpt,
    })),
  ];
  const unverified = message.unsupported || [];
  const content = message.content || "";

  async function copy() {
    try {
      await navigator.clipboard.writeText(content.replace(/\[\d+\]/g, ""));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard can be blocked; nothing to undo.
    }
  }

  if (message.streaming && !content) {
    return (
      <div className="thinking-row" role="status">
        <div className="thinking" aria-hidden="true"><span /><span /><span /></div>
        {message.status && <span className="thinking-status">{message.status}</span>}
      </div>
    );
  }

  return (
    <article className="answer" aria-busy={message.streaming || undefined}>
      {content && (
        <div className="answer-copy">
          {content.split("\n\n").map((paragraph, index) => (
            <p key={index}>{withCitationMarks(paragraph)}</p>
          ))}
          {message.streaming && <span className="caret" aria-hidden="true" />}
        </div>
      )}

      {message.error && (
        <div className="answer-error" role="alert">
          <span>{message.error.message}</span>
          {onRetry && message.error.code !== "daily_budget_reached" && (
            <button type="button" onClick={onRetry}>
              <RotateCcw size={13} /> Retry
            </button>
          )}
        </div>
      )}

      {!message.streaming && !message.error && (
        <div className="answer-meta">
          {sources.length > 0 && (
            <button
              className="meta-button"
              type="button"
              aria-expanded={showSources}
              onClick={() => setShowSources((open) => !open)}
            >
              {sources.length} {sources.length === 1 ? "source" : "sources"}
              <ChevronDown size={13} className={showSources ? "flipped" : ""} />
            </button>
          )}
          {message.stopped && <span className="meta-note">Stopped</span>}
          {message.mode === "general" && <span className="meta-note">Not from your documents</span>}
          {unverified.length > 0 && (
            <span className="meta-note warn" title={unverified.join("\n")}>
              {unverified.length === 1 ? "1 line unverified" : `${unverified.length} lines unverified`}
            </span>
          )}
          {content && (
            <button className="meta-icon" type="button" onClick={copy} aria-label="Copy answer">
              {copied ? <Check size={13} /> : <Copy size={13} />}
            </button>
          )}
        </div>
      )}

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
                {source.file && (
                  <span className="source-file">
                    {source.file}{source.page ? ` · p. ${source.page}` : ""}
                  </span>
                )}
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

/** A stored message from the API, in the shape the components use. */
export function fromServer(message) {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    citations: message.citations || [],
    unsupported: message.unsupported_claims || [],
    mode: message.mode,
    webSources: [],
  };
}

import { useEffect, useRef, useState } from "react";
import type { ChatMeta } from "../types";
import { api, streamMessage, type BrowserStep, type UploadResponse } from "../api/client";

interface Props {
  chat: ChatMeta;
  onToggleBrowser: (enabled: boolean) => void;
  onDocUpdated: () => void;
}

interface Message {
  role: "user" | "agent" | "system";
  text: string;
  toolCalls?: { name: string; args: Record<string, unknown> }[];
  browserSteps?: BrowserStep[];
  upload?: UploadResponse;
  error?: string;
  streaming?: boolean;
}

export function ChatPanel({ chat, onToggleBrowser, onDocUpdated }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Reset local chat state when the active chat changes — chat history is
  // ephemeral by design (documents persist, conversations don't).
  useEffect(() => {
    setMessages([]);
    setDraft("");
    setUploading(false);
    abortRef.current?.abort();
    abortRef.current = null;
  }, [chat.id]);

  useEffect(() => {
    const el = scrollerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  async function send() {
    const text = draft.trim();
    if (!text || sending) return;
    setDraft("");
    setSending(true);

    setMessages((prev) => [
      ...prev,
      { role: "user", text },
      { role: "agent", text: "", streaming: true },
    ]);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamMessage(
        chat.id,
        text,
        (event) => {
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (!last || last.role !== "agent") return prev;

            if (event.type === "text") {
              next[next.length - 1] = { ...last, text: last.text + event.text };
            } else if (event.type === "tool_call") {
              const toolCalls = [...(last.toolCalls ?? []), { name: event.name, args: event.args }];
              next[next.length - 1] = { ...last, toolCalls };
            } else if (event.type === "browser_step") {
              const { type: _t, ...step } = event;
              void _t;
              const browserSteps = [...(last.browserSteps ?? []), step];
              next[next.length - 1] = { ...last, browserSteps };
            } else if (event.type === "doc_updated") {
              onDocUpdated();
            } else if (event.type === "error") {
              next[next.length - 1] = { ...last, error: event.message, streaming: false };
            } else if (event.type === "done") {
              next[next.length - 1] = { ...last, streaming: false };
            }
            return next;
          });
        },
        controller.signal,
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last && last.role === "agent") {
          next[next.length - 1] = { ...last, error: msg, streaming: false };
        }
        return next;
      });
    } finally {
      setSending(false);
      abortRef.current = null;
    }
  }

  async function handleFile(file: File) {
    if (uploading || sending) return;
    if (!file.type.startsWith("image/")) {
      setMessages((m) => [
        ...m,
        { role: "system", text: "", error: "Only image files can be uploaded for annotation." },
      ]);
      return;
    }
    setUploading(true);
    setMessages((m) => [
      ...m,
      { role: "user", text: `📎 Uploaded ${file.name}` },
      { role: "agent", text: `Annotating ${file.name}…`, streaming: true },
    ]);
    try {
      const result = await api.uploadImage(chat.id, file);
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last && last.role === "agent") {
          next[next.length - 1] = {
            role: "agent",
            text: `Detected ${result.element_count} interactive elements. Added the annotated screenshot and the table to **Screenshots And Assets**. Tell me anything that's wrong and I'll fix the table.`,
            upload: result,
            streaming: false,
          };
        }
        return next;
      });
      onDocUpdated();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last && last.role === "agent") {
          next[next.length - 1] = { ...last, error: msg, streaming: false };
        }
        return next;
      });
    } finally {
      setUploading(false);
    }
  }

  return (
    <section className="chat-panel">
      <div className="chat-header">
        <div className="chat-title">{chat.name}</div>
        <div className="chat-controls">
          <label className="toggle" title="Per-chat browser walkthrough toggle">
            <input
              type="checkbox"
              checked={chat.browser_enabled}
              onChange={(e) => onToggleBrowser(e.target.checked)}
            />
            <span>Browser walkthrough</span>
          </label>
        </div>
      </div>

      <div className="chat-messages" ref={scrollerRef}>
        {messages.length === 0 ? (
          <div className="chat-empty">
            Start by describing the product or feature. The agent will interview you and write the guide on the right.
          </div>
        ) : (
          messages.map((m, i) => <MessageBubble key={i} message={m} />)
        )}
      </div>

      <div className="chat-input-wrap">
        <div className="chat-input-row">
          <button
            type="button"
            className="attach-btn"
            title="Attach a screenshot for annotation"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading || sending}
          >
            📎
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            className="hidden-file"
            aria-label="Attach screenshot for annotation"
            title="Attach screenshot for annotation"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleFile(f);
              e.target.value = "";
            }}
          />
          <textarea
            className="chat-input"
            placeholder={
              sending
                ? "Agent is responding…"
                : uploading
                  ? "Annotating screenshot…"
                  : "Describe this page, answer the agent, or attach a screenshot…"
            }
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={sending || uploading}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={2}
          />
        </div>
        <div className="chat-input-hint">
          Enter to send · Shift+Enter for newline · 📎 to attach a page screenshot (any image, max 20 MB)
        </div>
      </div>
    </section>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const variant = message.role === "user" ? "user" : message.role === "system" ? "system" : "agent";
  return (
    <div className={`bubble ${variant}`}>
      {message.text ||
        (message.streaming &&
        !message.toolCalls?.length &&
        !message.browserSteps?.length &&
        !message.upload ? (
          <span className="bubble-stream-placeholder">…</span>
        ) : null)}
      {message.toolCalls?.map((tc, i) => (
        <div key={i} className="tool-call">
          <span className="tool-call-name">→ {tc.name}</span>
          {tc.name === "update_document_section" && tc.args.section_name ? (
            <span> ({String(tc.args.section_name)})</span>
          ) : null}
          {tc.name === "browser_open" && tc.args.url ? (
            <span> ({String(tc.args.url)})</span>
          ) : null}
          {(tc.name === "browser_click" || tc.name === "browser_fill") && tc.args.target ? (
            <span> ({String(tc.args.target)})</span>
          ) : null}
        </div>
      ))}
      {message.browserSteps?.map((step, i) => (
        <div key={i} className="browser-step">
          <div className="browser-step-action">{step.action}</div>
          <div className="browser-step-meta">
            <span>{step.title || "(untitled)"}</span>
            <span className="browser-step-url">{step.url}</span>
          </div>
          {step.screenshot_url ? (
            <img className="browser-step-img" src={step.screenshot_url} alt="Browser screenshot" />
          ) : null}
          {step.validation_messages.length > 0 ? (
            <div className="browser-step-validation">
              <b>Validation:</b> {step.validation_messages.join(" · ")}
            </div>
          ) : null}
          {step.notes ? <div className="browser-step-error">⚠ {step.notes}</div> : null}
        </div>
      ))}
      {message.upload ? (
        <div className="upload-preview">
          <img src={message.upload.annotated_url} alt="Annotated screenshot" />
          <div className="upload-summary">{message.upload.page_summary}</div>
          {message.upload.elements.length > 0 ? (
            <ol className="upload-elements">
              {message.upload.elements.slice(0, 8).map((el) => (
                <li key={el.index}>
                  <b>{el.label || `(unlabeled ${el.element_type})`}</b>
                  <span className="upload-element-kind"> · {el.element_type}</span>
                  <div className="upload-element-action">{el.inferred_action}</div>
                </li>
              ))}
              {message.upload.elements.length > 8 ? (
                <li className="upload-elements-more">
                  + {message.upload.elements.length - 8} more in the canvas table
                </li>
              ) : null}
            </ol>
          ) : null}
        </div>
      ) : null}
      {message.error ? <div className="bubble-error">{message.error}</div> : null}
    </div>
  );
}

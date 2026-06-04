import { useEffect, useRef, useState } from "react";
import type { ChatMeta } from "../types";
import { api, streamMessage, type AttachmentEvent, type BrowserStep } from "../api/client";
import { WavRecorder, micSupported } from "../lib/recorder";
import { BrowserConfigDialog } from "./BrowserConfigDialog";

interface Props {
  chat: ChatMeta;
  onChatUpdated: (updated: ChatMeta) => void;
  onDocUpdated: () => void;
}

type AttachKind = "image" | "pdf" | "video";

interface PendingAttachment {
  id: string;
  file: File;
  kind: AttachKind;
  previewUrl?: string;
}

interface SentAttachment {
  name: string;
  kind: AttachKind;
  previewUrl?: string;
}

interface Message {
  role: "user" | "agent" | "system";
  text: string;
  browse?: boolean;
  toolCalls?: { name: string; args: Record<string, unknown> }[];
  browserSteps?: BrowserStep[];
  attachments?: AttachmentEvent[];
  sentAttachments?: SentAttachment[];
  error?: string;
  interrupted?: boolean;
  streaming?: boolean;
}

const MAX_FILES = 8;
const MAX_BYTES = 20 * 1024 * 1024; // images & PDFs
const MAX_VIDEO_BYTES = 200 * 1024 * 1024; // screen recordings
// `/browse` at the very start of the message, followed by whitespace/end.
const BROWSE_RE = /^\/browse(\s[\s\S]*|)$/i;

function fileKind(file: File): AttachKind | null {
  if (file.type.startsWith("image/")) return "image";
  if (file.type === "application/pdf") return "pdf";
  if (file.type.startsWith("video/")) return "video";
  return null;
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Inline line icons (Feather-style) — crisp at any size, inherit currentColor.
const svgProps = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};
const IconPaperclip = () => (
  <svg {...svgProps}>
    <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
  </svg>
);
const IconGlobe = () => (
  <svg {...svgProps}>
    <circle cx="12" cy="12" r="10" />
    <path d="M2 12h20" />
    <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
  </svg>
);
const IconMic = () => (
  <svg {...svgProps}>
    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
    <line x1="12" y1="19" x2="12" y2="23" />
    <line x1="8" y1="23" x2="16" y2="23" />
  </svg>
);
const IconArrowUp = () => (
  <svg {...svgProps}>
    <line x1="12" y1="20" x2="12" y2="5" />
    <polyline points="5 12 12 5 19 12" />
  </svg>
);
const IconStop = () => (
  <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <rect x="6" y="6" width="12" height="12" rx="2" />
  </svg>
);
const IconFilm = () => (
  <svg {...svgProps}>
    <rect x="2.5" y="4" width="19" height="16" rx="2" />
    <path d="M7 4v16M17 4v16M2.5 9h4.5M2.5 15h4.5M17 9h4.5M17 15h4.5" />
  </svg>
);

export function ChatPanel({ chat, onChatUpdated, onDocUpdated }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [sending, setSending] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [preview, setPreview] = useState<{ url: string; name: string } | null>(null);
  const [showBrowserCfg, setShowBrowserCfg] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const highlightRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const objectUrlsRef = useRef<Set<string>>(new Set());
  // Voice input: record mic audio, then Gemini transcribes it on the backend.
  const recorderRef = useRef<WavRecorder | null>(null);

  const browseMode = BROWSE_RE.test(draft);
  const micOk = micSupported();

  useEffect(() => {
    setMessages([]);
    setDraft("");
    setAttachments([]);
    setDragActive(false);
    setShowBrowserCfg(false);
    abortRef.current?.abort();
    abortRef.current = null;
    recorderRef.current?.cancel();
    recorderRef.current = null;
    setRecording(false);
    setTranscribing(false);
  }, [chat.id]);

  useEffect(() => {
    const urls = objectUrlsRef.current;
    return () => {
      urls.forEach((u) => URL.revokeObjectURL(u));
      urls.clear();
      recorderRef.current?.cancel();
    };
  }, []);

  useEffect(() => {
    const el = scrollerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // Auto-grow the composer from one row up to its max, so the box hugs its
  // content instead of always reserving two rows of empty height. The overlay
  // is inset:0 over this textarea, so it tracks the height automatically.
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }, [draft]);

  function systemError(text: string) {
    setMessages((m) => [...m, { role: "system", text: "", error: text }]);
  }

  function addFiles(list: FileList | File[]) {
    const incoming = Array.from(list);
    if (incoming.length === 0) return;
    const accepted: PendingAttachment[] = [];
    for (const file of incoming) {
      const kind = fileKind(file);
      if (!kind) {
        systemError(`"${file.name}" was skipped — only images, PDFs, and videos can be attached.`);
        continue;
      }
      const limit = kind === "video" ? MAX_VIDEO_BYTES : MAX_BYTES;
      if (file.size > limit) {
        const cap = kind === "video" ? "200 MB" : "20 MB";
        systemError(`"${file.name}" was skipped — exceeds the ${cap} limit.`);
        continue;
      }
      let previewUrl: string | undefined;
      if (kind === "image" || kind === "video") {
        previewUrl = URL.createObjectURL(file);
        objectUrlsRef.current.add(previewUrl);
      }
      accepted.push({
        id: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
        file,
        kind,
        previewUrl,
      });
    }
    if (accepted.length === 0) return;
    setAttachments((prev) => {
      const combined = [...prev, ...accepted];
      if (combined.length > MAX_FILES) {
        systemError(`Only ${MAX_FILES} files can be attached per message; extra files were dropped.`);
        return combined.slice(0, MAX_FILES);
      }
      return combined;
    });
  }

  function removeAttachment(id: string) {
    setAttachments((prev) => {
      const found = prev.find((a) => a.id === id);
      if (found?.previewUrl) {
        URL.revokeObjectURL(found.previewUrl);
        objectUrlsRef.current.delete(found.previewUrl);
      }
      return prev.filter((a) => a.id !== id);
    });
  }

  function handlePaste(e: React.ClipboardEvent) {
    const files = Array.from(e.clipboardData.files ?? []);
    const usable = files.filter((f) => fileKind(f));
    if (usable.length > 0) {
      e.preventDefault();
      addFiles(usable);
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragActive(false);
    if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
  }

  function stop() {
    abortRef.current?.abort();
  }

  async function toggleMic() {
    if (transcribing) return;

    // Stop an in-progress recording → transcribe it with Gemini.
    if (recording) {
      const recorder = recorderRef.current;
      recorderRef.current = null;
      setRecording(false);
      if (!recorder) return;
      let blob: Blob | null = null;
      try {
        blob = await recorder.stop();
      } catch {
        blob = null;
      }
      if (!blob) {
        systemError("No audio was recorded — try holding the mic a moment longer.");
        return;
      }
      setTranscribing(true);
      try {
        const text = await api.transcribe(blob);
        if (text) {
          setDraft((d) => (d ? d.replace(/\s+$/, "") + " " : "") + text);
          textareaRef.current?.focus();
        } else {
          systemError("No speech was detected in the recording.");
        }
      } catch (e) {
        systemError(`Couldn't transcribe the audio: ${e instanceof Error ? e.message : String(e)}`);
      } finally {
        setTranscribing(false);
      }
      return;
    }

    // Start a new recording.
    if (!micOk) {
      systemError("Voice input isn't supported in this browser.");
      return;
    }
    const recorder = new WavRecorder();
    try {
      await recorder.start();
    } catch (e) {
      const denied = e instanceof DOMException && (e.name === "NotAllowedError" || e.name === "SecurityError");
      systemError(
        denied
          ? "Microphone access was blocked. Allow microphone access for this site, then try again."
          : `Couldn't start the microphone: ${e instanceof Error ? e.message : String(e)}`,
      );
      return;
    }
    recorderRef.current = recorder;
    setRecording(true);
  }

  async function send() {
    if (sending) return;
    const raw = draft.trim();
    let text = raw;
    let browse = false;
    const m = raw.match(BROWSE_RE);
    if (m) {
      browse = true;
      text = (m[1] ?? "").trim();
    }
    if (!text && attachments.length === 0 && !browse) return;

    const files = attachments.map((a) => a.file);
    const sent: SentAttachment[] = attachments.map((a) => ({
      name: a.file.name,
      kind: a.kind,
      previewUrl: a.previewUrl,
    }));

    setDraft("");
    setAttachments([]);
    setSending(true);

    setMessages((prev) => [
      ...prev,
      { role: "user", text, browse, sentAttachments: sent.length ? sent : undefined },
      { role: "agent", text: "", streaming: true },
    ]);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamMessage(
        chat.id,
        text,
        files,
        browse,
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
            } else if (event.type === "attachment") {
              const atts = [...(last.attachments ?? []), event];
              next[next.length - 1] = { ...last, attachments: atts };
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
      const aborted = controller.signal.aborted || (err instanceof DOMException && err.name === "AbortError");
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last && last.role === "agent") {
          next[next.length - 1] = aborted
            ? { ...last, interrupted: true, streaming: false }
            : { ...last, error: err instanceof Error ? err.message : String(err), streaming: false };
        }
        return next;
      });
    } finally {
      setSending(false);
      abortRef.current = null;
    }
  }

  const trimmed = draft.trim();
  const canSend = !sending && (trimmed.length > 0 || attachments.length > 0);

  return (
    <section
      className={`chat-panel${dragActive ? " chat-drop-active" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragActive(true);
      }}
      onDragLeave={(e) => {
        if (e.currentTarget === e.target) setDragActive(false);
      }}
      onDrop={handleDrop}
    >
      <div className="chat-header">
        <div className="chat-title">{chat.name}</div>
        {chat.browser_enabled && <span className="chat-browser-on" title="Browser walkthrough enabled">🌐 walkthrough on</span>}
      </div>

      <div className="chat-messages" ref={scrollerRef}>
        {messages.length === 0 ? (
          <div className="chat-empty">
            Start by describing the page. Attach screenshots, PDFs, or a screen recording (📎, paste, or drag &amp; drop), or type <code>/browse</code> to have the agent open and verify it live.
          </div>
        ) : (
          messages.map((m, i) => <MessageBubble key={i} message={m} onPreview={setPreview} />)
        )}
      </div>

      <div className="composer">
        {attachments.length > 0 && (
          <div className="attachment-chips">
            {attachments.map((a) => (
              <div
                key={a.id}
                className="attachment-chip"
                title={`${a.file.name} · ${fmtSize(a.file.size)} — click to preview`}
                onClick={() => {
                  if (a.kind === "image" && a.previewUrl) setPreview({ url: a.previewUrl, name: a.file.name });
                  else if (a.previewUrl) window.open(a.previewUrl, "_blank");
                }}
              >
                {a.kind === "image" && a.previewUrl ? (
                  <img src={a.previewUrl} alt={a.file.name} />
                ) : (
                  <span className="attachment-chip-icon">{a.kind === "video" ? <IconFilm /> : "📄"}</span>
                )}
                <span className="attachment-chip-name">{a.file.name}</span>
                <button
                  type="button"
                  className="attachment-chip-remove"
                  title="Remove attachment"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeAttachment(a.id);
                  }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}

        <div className={`composer-row${browseMode ? " browse-active" : ""}`}>
          <div className="composer-icons">
            <button
              type="button"
              className="icon-btn"
              title="Attach screenshots, PDFs, or screen recordings"
              aria-label="Attach files"
              onClick={() => fileInputRef.current?.click()}
            >
              <IconPaperclip />
            </button>
            <button
              type="button"
              className={`icon-btn${chat.browser_enabled ? " on" : ""}`}
              title="Browser walkthrough settings (URL, login, notes)"
              aria-label="Browser walkthrough settings"
              onClick={() => setShowBrowserCfg(true)}
            >
              <IconGlobe />
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*,application/pdf,video/*"
              multiple
              className="hidden-file"
              aria-label="Attach screenshots, PDFs, or screen recordings"
              onChange={(e) => {
                if (e.target.files?.length) addFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>

          <div className="composer-input">
            <div className="input-highlight" ref={highlightRef} aria-hidden="true" dir="auto">
              {renderHighlight(draft)}
            </div>
            <textarea
              ref={textareaRef}
              className="composer-textarea"
              placeholder="Message the agent…"
              value={draft}
              dir="auto"
              onChange={(e) => setDraft(e.target.value)}
              onPaste={handlePaste}
              onScroll={(e) => {
                if (highlightRef.current) highlightRef.current.scrollTop = e.currentTarget.scrollTop;
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              rows={1}
            />
          </div>

          <div className="composer-actions">
            <button
              type="button"
              className={`icon-btn${recording ? " recording" : ""}${transcribing ? " busy" : ""}`}
              onClick={toggleMic}
              disabled={!micOk || transcribing}
              title={
                !micOk
                  ? "Voice input isn't supported in this browser"
                  : transcribing
                    ? "Transcribing…"
                    : recording
                      ? "Stop and transcribe"
                      : "Voice input (Gemini transcribes your recording)"
              }
              aria-label="Voice input"
            >
              {transcribing ? <span className="mini-spinner" /> : recording ? <IconStop /> : <IconMic />}
            </button>

            {sending ? (
              <button
                type="button"
                className="composer-send stop-btn"
                onClick={stop}
                title="Stop generating"
                aria-label="Stop generating"
              >
                <IconStop />
              </button>
            ) : (
              <button
                type="button"
                className="composer-send send-btn"
                onClick={send}
                disabled={!canSend}
                title="Send"
                aria-label="Send message"
              >
                <IconArrowUp />
              </button>
            )}
          </div>
        </div>

        <div className="composer-hint">
          {recording
            ? "● Recording… click the mic again to stop and transcribe."
            : transcribing
              ? "Transcribing your recording…"
              : sending
                ? "Agent is responding — keep typing; press Stop to interrupt, then send."
                : browseMode
                  ? "Browse mode: the agent will open & verify the page using your saved settings."
                  : "Enter to send · Shift+Enter for newline · attach images, PDFs & recordings · /browse to verify live"}
        </div>
      </div>

      {preview && (
        <div className="attachment-preview-backdrop" onClick={() => setPreview(null)}>
          <div className="attachment-preview-modal" onClick={(e) => e.stopPropagation()}>
            <div className="attachment-preview-head">
              <span>{preview.name}</span>
              <button type="button" className="attachment-preview-close" onClick={() => setPreview(null)}>
                ×
              </button>
            </div>
            <img src={preview.url} alt={preview.name} />
          </div>
        </div>
      )}

      {showBrowserCfg && (
        <BrowserConfigDialog chat={chat} onClose={() => setShowBrowserCfg(false)} onSaved={onChatUpdated} />
      )}
    </section>
  );
}

function renderHighlight(text: string) {
  const m = text.match(BROWSE_RE);
  if (m) {
    return (
      <>
        <span className="cmd-token">/browse</span>
        {m[1]}
        {"​"}
      </>
    );
  }
  return <>{text}{"​"}</>;
}

function MessageBubble({
  message,
  onPreview,
}: {
  message: Message;
  onPreview: (p: { url: string; name: string }) => void;
}) {
  const variant = message.role === "user" ? "user" : message.role === "system" ? "system" : "agent";
  const hasExtras =
    !!message.toolCalls?.length ||
    !!message.browserSteps?.length ||
    !!message.attachments?.length ||
    !!message.sentAttachments?.length;
  return (
    <div className={`bubble ${variant}`} dir="auto">
      {message.role === "user" && message.browse ? <span className="browse-tag" dir="ltr">/browse</span> : null}
      {message.text ||
        (message.streaming && !hasExtras ? <span className="bubble-stream-placeholder">…</span> : null)}

      {message.sentAttachments && message.sentAttachments.length > 0 ? (
        <div className="sent-attachments">
          {message.sentAttachments.map((a, i) =>
            a.kind === "image" && a.previewUrl ? (
              <img
                key={i}
                className="sent-attachment-thumb"
                src={a.previewUrl}
                alt={a.name}
                title={`${a.name} — click to preview`}
                onClick={() => onPreview({ url: a.previewUrl!, name: a.name })}
              />
            ) : (
              <span key={i} className="attachment-pill" title={a.name}>
                {a.kind === "video" ? <IconFilm /> : "📄"} {a.name}
              </span>
            ),
          )}
        </div>
      ) : null}

      {message.toolCalls?.map((tc, i) => (
        <div key={i} className="tool-call" dir="ltr">
          <span className="tool-call-name">→ {tc.name}</span>
          {tc.name === "update_document_section" && tc.args.section_name ? (
            <span> ({String(tc.args.section_name)})</span>
          ) : null}
          {tc.name === "browser_open" && tc.args.url ? <span> ({String(tc.args.url)})</span> : null}
          {(tc.name === "browser_click" || tc.name === "browser_fill") && tc.args.target ? (
            <span> ({String(tc.args.target)})</span>
          ) : null}
        </div>
      ))}

      {message.browserSteps?.map((step, i) => (
        <div key={i} className="browser-step" dir="ltr">
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

      {message.attachments?.map((att, i) =>
        att.kind === "image" ? (
          <div key={i} className="upload-preview">
            {att.error ? (
              <div className="bubble-error">Could not annotate {att.name}: {att.error}</div>
            ) : (
              <>
                {att.annotated_url ? (
                  <img
                    src={att.annotated_url}
                    alt="Annotated screenshot"
                    onClick={() => onPreview({ url: att.annotated_url!, name: att.name })}
                  />
                ) : null}
                {att.page_summary ? <div className="upload-summary">{att.page_summary}</div> : null}
                {att.elements && att.elements.length > 0 ? (
                  <ol className="upload-elements">
                    {att.elements.slice(0, 8).map((el) => (
                      <li key={el.index}>
                        <b>{el.label || `(unlabeled ${el.element_type})`}</b>
                        <span className="upload-element-kind">
                          {" "}· {el.element_type}
                          {el.is_repeated_group && (el.instance_count ?? 1) > 1
                            ? ` (repeated ×${el.instance_count})`
                            : ""}
                        </span>
                        <div className="upload-element-action">{el.inferred_action}</div>
                      </li>
                    ))}
                    {(att.element_count ?? att.elements.length) > 8 ? (
                      <li className="upload-elements-more">
                        + {(att.element_count ?? att.elements.length) - 8} more in the canvas table
                      </li>
                    ) : null}
                  </ol>
                ) : null}
              </>
            )}
          </div>
        ) : att.kind === "video" ? (
          <div key={i} className="upload-preview">
            {att.error ? (
              <div className="bubble-error">Couldn't analyze {att.name}: {att.error}</div>
            ) : null}
            <a className="attachment-pill attachment-pill-link" href={att.file_url} target="_blank" rel="noreferrer">
              <IconFilm /> {att.name} — screen recording linked
            </a>
          </div>
        ) : (
          <a key={i} className="attachment-pill attachment-pill-link" href={att.file_url} target="_blank" rel="noreferrer">
            📄 {att.name} — linked in document
          </a>
        ),
      )}

      {message.interrupted ? <div className="bubble-interrupted">■ interrupted</div> : null}
      {message.error ? <div className="bubble-error">{message.error}</div> : null}
    </div>
  );
}

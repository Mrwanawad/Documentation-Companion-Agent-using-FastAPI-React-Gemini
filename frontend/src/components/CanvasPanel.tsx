import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { DocumentRead } from "../types";
import { api } from "../api/client";

interface Props {
  chatId: string;
  version: string;
  readonly: boolean;
  refreshSignal: number;
}

type Mode = "preview" | "edit";

export function CanvasPanel({ chatId, version, readonly, refreshSignal }: Props) {
  const [doc, setDoc] = useState<DocumentRead | null>(null);
  const [mode, setMode] = useState<Mode>("preview");
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.getDocument(chatId).then((d) => {
      if (cancelled) return;
      setDoc(d);
      // Only sync draft from server when not actively editing — otherwise an
      // agent-triggered refresh would clobber in-flight typing.
      setDraft((current) => (current === "" ? d.content : current));
    });
    return () => {
      cancelled = true;
    };
  }, [chatId, refreshSignal]);

  async function save() {
    if (saving || readonly) return;
    setSaving(true);
    try {
      const updated = await api.writeDocument(chatId, draft);
      setDoc(updated);
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="canvas-panel">
      <div className="canvas-header">
        <div className="canvas-tabs">
          <button
            type="button"
            className={`canvas-tab${mode === "preview" ? " active" : ""}`}
            onClick={() => setMode("preview")}
          >
            Preview
          </button>
          <button
            type="button"
            className={`canvas-tab${mode === "edit" ? " active" : ""}`}
            onClick={() => setMode("edit")}
            disabled={readonly}
            title={readonly ? "Approved documents are readonly" : ""}
          >
            Edit
          </button>
        </div>
        <div className="canvas-meta">
          <span>{version}</span>
          {readonly && <span className="readonly-pill">· readonly</span>}
          {mode === "edit" && (
            <button
              type="button"
              className="btn btn-primary btn-inline"
              onClick={save}
              disabled={saving || draft === doc?.content}
            >
              {saving ? "Saving…" : "Save"}
            </button>
          )}
        </div>
      </div>

      <div className="canvas-body">
        {doc === null ? (
          <div className="canvas-empty">Loading document…</div>
        ) : mode === "preview" ? (
          <div className="md">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{doc.content}</ReactMarkdown>
          </div>
        ) : (
          <textarea
            className="canvas-editor"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            spellCheck={false}
          />
        )}
      </div>
    </section>
  );
}

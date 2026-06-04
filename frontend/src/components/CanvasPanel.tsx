import { useCallback, useEffect, useRef, useState } from "react";
import { Editor, rootCtx, defaultValueCtx, editorViewOptionsCtx } from "@milkdown/core";
import { Milkdown, MilkdownProvider, useEditor } from "@milkdown/react";
import { commonmark } from "@milkdown/preset-commonmark";
import { gfm } from "@milkdown/preset-gfm";
import { listener, listenerCtx } from "@milkdown/plugin-listener";
import { getMarkdown, replaceAll } from "@milkdown/utils";
import { nord } from "@milkdown/theme-nord";
import "@milkdown/theme-nord/style.css";
import { api } from "../api/client";

// Pick the document's writing direction from its content so an Arabic guide
// lays out right-to-left without needing any per-chat flag threaded down here.
const RTL_CHARS = /[֑-߿יִ-﷽ﹰ-ﻼ]/g;
const LTR_CHARS = /[A-Za-zÀ-ɏ]/g;
function detectDir(text: string): "ltr" | "rtl" {
  const rtl = (text.match(RTL_CHARS) || []).length;
  if (rtl === 0) return "ltr";
  const ltr = (text.match(LTR_CHARS) || []).length;
  return rtl > ltr ? "rtl" : "ltr";
}

interface Props {
  chatId: string;
  version: string;
  readonly: boolean;
  refreshSignal: number;
  onCollapse: () => void;
}

type GetEditor = () => Editor | undefined;

type Mode = "rich" | "source";

function MilkdownDoc({
  initial,
  editable,
  onReady,
  onChange,
}: {
  initial: string;
  editable: boolean;
  onReady: (get: GetEditor) => void;
  onChange: (md: string) => void;
}) {
  const editableRef = useRef(editable);
  editableRef.current = editable;

  const { get } = useEditor((root) =>
    Editor.make()
      .config((ctx) => {
        ctx.set(rootCtx, root);
        ctx.set(defaultValueCtx, initial);
        ctx.update(editorViewOptionsCtx, (prev) => ({ ...prev, editable: () => editableRef.current }));
        ctx.get(listenerCtx).markdownUpdated((_ctx, md) => onChange(md));
      })
      .config(nord)
      .use(listener)
      .use(commonmark)
      .use(gfm),
  );

  useEffect(() => {
    onReady(get);
  }, [get, onReady]);

  return <Milkdown />;
}

export function CanvasPanel({ chatId, version, readonly, refreshSignal, onCollapse }: Props) {
  const [loaded, setLoaded] = useState(false);
  const [initial, setInitial] = useState("");
  const [mode, setMode] = useState<Mode>("rich");
  const [sourceDraft, setSourceDraft] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [pendingUpdate, setPendingUpdate] = useState(false);

  const getRef = useRef<GetEditor | null>(null);
  const serverMdRef = useRef("");   // baseline (editor's serialization of saved content)
  const pendingDocRef = useRef(""); // latest server content while user has unsaved edits
  const modeRef = useRef<Mode>("rich");
  modeRef.current = mode;
  const baselineReadyRef = useRef(false); // re-baseline the editor on next poll tick

  const editorMd = useCallback((): string | null => {
    const ed = getRef.current?.();
    if (!ed) return null;
    try {
      return ed.action(getMarkdown());
    } catch {
      return null;
    }
  }, []);

  // Initial load (component is remounted per chat via key, so this runs fresh).
  useEffect(() => {
    let cancelled = false;
    api.getDocument(chatId).then((d) => {
      if (cancelled) return;
      serverMdRef.current = d.content;
      pendingDocRef.current = d.content;
      setInitial(d.content);
      setSourceDraft(d.content);
      setLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, [chatId]);

  // Agent updated the document (refreshSignal bumps). Skip the first render.
  const firstSignal = useRef(true);
  useEffect(() => {
    if (firstSignal.current) {
      firstSignal.current = false;
      return;
    }
    let cancelled = false;
    api.getDocument(chatId).then((d) => {
      if (cancelled) return;
      pendingDocRef.current = d.content;
      if (dirty) {
        setPendingUpdate(true); // don't clobber unsaved edits
      } else {
        getRef.current?.()?.action(replaceAll(d.content));
        setSourceDraft(d.content);
        baselineReadyRef.current = false; // poll re-baselines from new content
      }
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal]);

  const onReady = useCallback((get: GetEditor) => {
    getRef.current = get;
  }, []);

  const onEditorChange = useCallback(
    (md: string) => {
      if (modeRef.current === "rich") setDirty(md !== serverMdRef.current);
    },
    [],
  );

  // Dirty-detection by polling the editor's serialized markdown. Robust against
  // Milkdown's async mount / listener-wiring quirks. Only meaningful in rich
  // mode; source mode tracks dirty via the textarea's onChange. A re-baseline
  // flag lets programmatic content swaps (load, save, agent reload) reset cleanly.
  useEffect(() => {
    if (!loaded) return;
    baselineReadyRef.current = false;
    const id = window.setInterval(() => {
      const md = editorMd();
      if (md == null) return; // editor not mounted yet
      if (!baselineReadyRef.current) {
        serverMdRef.current = md;
        baselineReadyRef.current = true;
        setDirty(false);
        return;
      }
      if (modeRef.current === "rich") setDirty(md !== serverMdRef.current);
    }, 500);
    return () => window.clearInterval(id);
  }, [loaded, editorMd]);

  function toggleMode() {
    if (mode === "rich") {
      setSourceDraft(editorMd() ?? sourceDraft);
      setMode("source");
    } else {
      getRef.current?.()?.action(replaceAll(sourceDraft));
      setMode("rich");
    }
  }

  async function save() {
    if (saving || readonly || !dirty) return;
    const content = mode === "rich" ? editorMd() ?? "" : sourceDraft;
    setSaving(true);
    try {
      const updated = await api.writeDocument(chatId, content);
      serverMdRef.current = content;
      pendingDocRef.current = updated.content;
      setSourceDraft(content);
      if (mode === "source") getRef.current?.()?.action(replaceAll(content));
      setDirty(false);
      baselineReadyRef.current = false; // poll re-baselines from saved content
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  }

  function reloadFromServer() {
    const c = pendingDocRef.current;
    getRef.current?.()?.action(replaceAll(c));
    setSourceDraft(c);
    setDirty(false);
    setPendingUpdate(false);
    baselineReadyRef.current = false; // poll re-baselines from reloaded content
  }

  const docDir = detectDir(sourceDraft || initial);

  return (
    <section className="canvas-panel">
      <div className="canvas-header">
        <div className="canvas-meta">
          <button type="button" className="canvas-collapse" title="Hide document" onClick={onCollapse}>
            ›
          </button>
          <span>{version}</span>
          {readonly && <span className="readonly-pill">· readonly</span>}
          {dirty && !readonly && <span className="dirty-dot" title="Unsaved changes">●</span>}
        </div>
        <div className="canvas-actions">
          <button
            type="button"
            className={`canvas-btn${mode === "source" ? " active" : ""}`}
            onClick={toggleMode}
            title={mode === "source" ? "Formatted editor" : "Edit Markdown source"}
          >
            {mode === "source" ? "◑ Rich" : "</> Source"}
          </button>
          <a className="canvas-btn" href={api.exportUrl(chatId)} download title="Download as HTML (images included)">
            ⬇ Download
          </a>
          {!readonly && (
            <button
              type="button"
              className="btn btn-primary btn-inline"
              onClick={save}
              disabled={saving || !dirty}
            >
              {saving ? "Saving…" : "Save"}
            </button>
          )}
        </div>
      </div>

      {pendingUpdate && (
        <div className="canvas-banner">
          <span>The agent updated this document.</span>
          <div className="canvas-banner-actions">
            <button type="button" className="canvas-btn" onClick={reloadFromServer}>
              Reload
            </button>
            <button type="button" className="canvas-btn" onClick={() => setPendingUpdate(false)}>
              Keep mine
            </button>
          </div>
        </div>
      )}

      <div className="canvas-body">
        {!loaded ? (
          <div className="canvas-empty">Loading document…</div>
        ) : (
          <>
            <div
              className="md-editor"
              dir={docDir}
              style={{ display: mode === "source" ? "none" : "block" }}
            >
              <MilkdownProvider>
                <MilkdownDoc initial={initial} editable={!readonly} onReady={onReady} onChange={onEditorChange} />
              </MilkdownProvider>
            </div>
            {mode === "source" && (
              <textarea
                className="canvas-editor"
                aria-label="Markdown source"
                placeholder="Markdown source…"
                value={sourceDraft}
                dir="auto"
                spellCheck={false}
                readOnly={readonly}
                onChange={(e) => {
                  setSourceDraft(e.target.value);
                  setDirty(e.target.value !== serverMdRef.current);
                }}
              />
            )}
          </>
        )}
      </div>
    </section>
  );
}

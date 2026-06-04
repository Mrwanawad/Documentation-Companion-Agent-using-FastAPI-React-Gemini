import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
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
function MilkdownDoc({ initial, editable, onReady, onChange, }) {
    const editableRef = useRef(editable);
    editableRef.current = editable;
    const { get } = useEditor((root) => Editor.make()
        .config((ctx) => {
        ctx.set(rootCtx, root);
        ctx.set(defaultValueCtx, initial);
        ctx.update(editorViewOptionsCtx, (prev) => ({ ...prev, editable: () => editableRef.current }));
        ctx.get(listenerCtx).markdownUpdated((_ctx, md) => onChange(md));
    })
        .config(nord)
        .use(listener)
        .use(commonmark)
        .use(gfm));
    useEffect(() => {
        onReady(get);
    }, [get, onReady]);
    return _jsx(Milkdown, {});
}
export function CanvasPanel({ chatId, version, readonly, refreshSignal, onCollapse }) {
    const [loaded, setLoaded] = useState(false);
    const [initial, setInitial] = useState("");
    const [mode, setMode] = useState("rich");
    const [sourceDraft, setSourceDraft] = useState("");
    const [dirty, setDirty] = useState(false);
    const [saving, setSaving] = useState(false);
    const [pendingUpdate, setPendingUpdate] = useState(false);
    const getRef = useRef(null);
    const serverMdRef = useRef(""); // baseline (editor's serialization of saved content)
    const pendingDocRef = useRef(""); // latest server content while user has unsaved edits
    const modeRef = useRef("rich");
    modeRef.current = mode;
    const baselineReadyRef = useRef(false); // re-baseline the editor on next poll tick
    const editorMd = useCallback(() => {
        const ed = getRef.current?.();
        if (!ed)
            return null;
        try {
            return ed.action(getMarkdown());
        }
        catch {
            return null;
        }
    }, []);
    // Initial load (component is remounted per chat via key, so this runs fresh).
    useEffect(() => {
        let cancelled = false;
        api.getDocument(chatId).then((d) => {
            if (cancelled)
                return;
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
            if (cancelled)
                return;
            pendingDocRef.current = d.content;
            if (dirty) {
                setPendingUpdate(true); // don't clobber unsaved edits
            }
            else {
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
    const onReady = useCallback((get) => {
        getRef.current = get;
    }, []);
    const onEditorChange = useCallback((md) => {
        if (modeRef.current === "rich")
            setDirty(md !== serverMdRef.current);
    }, []);
    // Dirty-detection by polling the editor's serialized markdown. Robust against
    // Milkdown's async mount / listener-wiring quirks. Only meaningful in rich
    // mode; source mode tracks dirty via the textarea's onChange. A re-baseline
    // flag lets programmatic content swaps (load, save, agent reload) reset cleanly.
    useEffect(() => {
        if (!loaded)
            return;
        baselineReadyRef.current = false;
        const id = window.setInterval(() => {
            const md = editorMd();
            if (md == null)
                return; // editor not mounted yet
            if (!baselineReadyRef.current) {
                serverMdRef.current = md;
                baselineReadyRef.current = true;
                setDirty(false);
                return;
            }
            if (modeRef.current === "rich")
                setDirty(md !== serverMdRef.current);
        }, 500);
        return () => window.clearInterval(id);
    }, [loaded, editorMd]);
    function toggleMode() {
        if (mode === "rich") {
            setSourceDraft(editorMd() ?? sourceDraft);
            setMode("source");
        }
        else {
            getRef.current?.()?.action(replaceAll(sourceDraft));
            setMode("rich");
        }
    }
    async function save() {
        if (saving || readonly || !dirty)
            return;
        const content = mode === "rich" ? editorMd() ?? "" : sourceDraft;
        setSaving(true);
        try {
            const updated = await api.writeDocument(chatId, content);
            serverMdRef.current = content;
            pendingDocRef.current = updated.content;
            setSourceDraft(content);
            if (mode === "source")
                getRef.current?.()?.action(replaceAll(content));
            setDirty(false);
            baselineReadyRef.current = false; // poll re-baselines from saved content
        }
        catch (e) {
            console.error(e);
        }
        finally {
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
    return (_jsxs("section", { className: "canvas-panel", children: [_jsxs("div", { className: "canvas-header", children: [_jsxs("div", { className: "canvas-meta", children: [_jsx("button", { type: "button", className: "canvas-collapse", title: "Hide document", onClick: onCollapse, children: "\u203A" }), _jsx("span", { children: version }), readonly && _jsx("span", { className: "readonly-pill", children: "\u00B7 readonly" }), dirty && !readonly && _jsx("span", { className: "dirty-dot", title: "Unsaved changes", children: "\u25CF" })] }), _jsxs("div", { className: "canvas-actions", children: [_jsx("button", { type: "button", className: `canvas-btn${mode === "source" ? " active" : ""}`, onClick: toggleMode, title: mode === "source" ? "Formatted editor" : "Edit Markdown source", children: mode === "source" ? "◑ Rich" : "</> Source" }), _jsx("a", { className: "canvas-btn", href: api.exportUrl(chatId), download: true, title: "Download as HTML (images included)", children: "\u2B07 Download" }), !readonly && (_jsx("button", { type: "button", className: "btn btn-primary btn-inline", onClick: save, disabled: saving || !dirty, children: saving ? "Saving…" : "Save" }))] })] }), pendingUpdate && (_jsxs("div", { className: "canvas-banner", children: [_jsx("span", { children: "The agent updated this document." }), _jsxs("div", { className: "canvas-banner-actions", children: [_jsx("button", { type: "button", className: "canvas-btn", onClick: reloadFromServer, children: "Reload" }), _jsx("button", { type: "button", className: "canvas-btn", onClick: () => setPendingUpdate(false), children: "Keep mine" })] })] })), _jsx("div", { className: "canvas-body", children: !loaded ? (_jsx("div", { className: "canvas-empty", children: "Loading document\u2026" })) : (_jsxs(_Fragment, { children: [_jsx("div", { className: "md-editor", style: { display: mode === "source" ? "none" : "block" }, children: _jsx(MilkdownProvider, { children: _jsx(MilkdownDoc, { initial: initial, editable: !readonly, onReady: onReady, onChange: onEditorChange }) }) }), mode === "source" && (_jsx("textarea", { className: "canvas-editor", "aria-label": "Markdown source", placeholder: "Markdown source\u2026", value: sourceDraft, spellCheck: false, readOnly: readonly, onChange: (e) => {
                                setSourceDraft(e.target.value);
                                setDirty(e.target.value !== serverMdRef.current);
                            } }))] })) })] }));
}

import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../api/client";
export function CanvasPanel({ chatId, version, readonly, refreshSignal }) {
    const [doc, setDoc] = useState(null);
    const [mode, setMode] = useState("preview");
    const [draft, setDraft] = useState("");
    const [saving, setSaving] = useState(false);
    useEffect(() => {
        let cancelled = false;
        api.getDocument(chatId).then((d) => {
            if (cancelled)
                return;
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
        if (saving || readonly)
            return;
        setSaving(true);
        try {
            const updated = await api.writeDocument(chatId, draft);
            setDoc(updated);
        }
        catch (e) {
            console.error(e);
        }
        finally {
            setSaving(false);
        }
    }
    return (_jsxs("section", { className: "canvas-panel", children: [_jsxs("div", { className: "canvas-header", children: [_jsxs("div", { className: "canvas-tabs", children: [_jsx("button", { type: "button", className: `canvas-tab${mode === "preview" ? " active" : ""}`, onClick: () => setMode("preview"), children: "Preview" }), _jsx("button", { type: "button", className: `canvas-tab${mode === "edit" ? " active" : ""}`, onClick: () => setMode("edit"), disabled: readonly, title: readonly ? "Approved documents are readonly" : "", children: "Edit" })] }), _jsxs("div", { className: "canvas-meta", children: [_jsx("span", { children: version }), readonly && _jsx("span", { className: "readonly-pill", children: "\u00B7 readonly" }), mode === "edit" && (_jsx("button", { type: "button", className: "btn btn-primary btn-inline", onClick: save, disabled: saving || draft === doc?.content, children: saving ? "Saving…" : "Save" }))] })] }), _jsx("div", { className: "canvas-body", children: doc === null ? (_jsx("div", { className: "canvas-empty", children: "Loading document\u2026" })) : mode === "preview" ? (_jsx("div", { className: "md", children: _jsx(ReactMarkdown, { remarkPlugins: [remarkGfm], children: doc.content }) })) : (_jsx("textarea", { className: "canvas-editor", value: draft, onChange: (e) => setDraft(e.target.value), spellCheck: false })) })] }));
}

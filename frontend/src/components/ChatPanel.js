import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { streamMessage } from "../api/client";
import { BrowserConfigDialog } from "./BrowserConfigDialog";
const MAX_FILES = 8;
const MAX_BYTES = 20 * 1024 * 1024;
// `/browse` at the very start of the message, followed by whitespace/end.
const BROWSE_RE = /^\/browse(\s[\s\S]*|)$/i;
function fileKind(file) {
    if (file.type.startsWith("image/"))
        return "image";
    if (file.type === "application/pdf")
        return "pdf";
    return null;
}
function fmtSize(bytes) {
    if (bytes < 1024)
        return `${bytes} B`;
    if (bytes < 1024 * 1024)
        return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
export function ChatPanel({ chat, onChatUpdated, onDocUpdated }) {
    const [messages, setMessages] = useState([]);
    const [draft, setDraft] = useState("");
    const [attachments, setAttachments] = useState([]);
    const [sending, setSending] = useState(false);
    const [dragActive, setDragActive] = useState(false);
    const [preview, setPreview] = useState(null);
    const [showBrowserCfg, setShowBrowserCfg] = useState(false);
    const scrollerRef = useRef(null);
    const abortRef = useRef(null);
    const fileInputRef = useRef(null);
    const highlightRef = useRef(null);
    const objectUrlsRef = useRef(new Set());
    const browseMode = BROWSE_RE.test(draft);
    useEffect(() => {
        setMessages([]);
        setDraft("");
        setAttachments([]);
        setDragActive(false);
        setShowBrowserCfg(false);
        abortRef.current?.abort();
        abortRef.current = null;
    }, [chat.id]);
    useEffect(() => {
        const urls = objectUrlsRef.current;
        return () => {
            urls.forEach((u) => URL.revokeObjectURL(u));
            urls.clear();
        };
    }, []);
    useEffect(() => {
        const el = scrollerRef.current;
        if (el)
            el.scrollTop = el.scrollHeight;
    }, [messages]);
    function systemError(text) {
        setMessages((m) => [...m, { role: "system", text: "", error: text }]);
    }
    function addFiles(list) {
        const incoming = Array.from(list);
        if (incoming.length === 0)
            return;
        const accepted = [];
        for (const file of incoming) {
            const kind = fileKind(file);
            if (!kind) {
                systemError(`"${file.name}" was skipped — only images and PDFs can be attached.`);
                continue;
            }
            if (file.size > MAX_BYTES) {
                systemError(`"${file.name}" was skipped — exceeds the 20 MB limit.`);
                continue;
            }
            let previewUrl;
            if (kind === "image") {
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
        if (accepted.length === 0)
            return;
        setAttachments((prev) => {
            const combined = [...prev, ...accepted];
            if (combined.length > MAX_FILES) {
                systemError(`Only ${MAX_FILES} files can be attached per message; extra files were dropped.`);
                return combined.slice(0, MAX_FILES);
            }
            return combined;
        });
    }
    function removeAttachment(id) {
        setAttachments((prev) => {
            const found = prev.find((a) => a.id === id);
            if (found?.previewUrl) {
                URL.revokeObjectURL(found.previewUrl);
                objectUrlsRef.current.delete(found.previewUrl);
            }
            return prev.filter((a) => a.id !== id);
        });
    }
    function handlePaste(e) {
        const files = Array.from(e.clipboardData.files ?? []);
        const usable = files.filter((f) => fileKind(f));
        if (usable.length > 0) {
            e.preventDefault();
            addFiles(usable);
        }
    }
    function handleDrop(e) {
        e.preventDefault();
        setDragActive(false);
        if (e.dataTransfer.files?.length)
            addFiles(e.dataTransfer.files);
    }
    function stop() {
        abortRef.current?.abort();
    }
    async function send() {
        if (sending)
            return;
        const raw = draft.trim();
        let text = raw;
        let browse = false;
        const m = raw.match(BROWSE_RE);
        if (m) {
            browse = true;
            text = (m[1] ?? "").trim();
        }
        if (!text && attachments.length === 0 && !browse)
            return;
        const files = attachments.map((a) => a.file);
        const sent = attachments.map((a) => ({
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
            await streamMessage(chat.id, text, files, browse, (event) => {
                setMessages((prev) => {
                    const next = [...prev];
                    const last = next[next.length - 1];
                    if (!last || last.role !== "agent")
                        return prev;
                    if (event.type === "text") {
                        next[next.length - 1] = { ...last, text: last.text + event.text };
                    }
                    else if (event.type === "tool_call") {
                        const toolCalls = [...(last.toolCalls ?? []), { name: event.name, args: event.args }];
                        next[next.length - 1] = { ...last, toolCalls };
                    }
                    else if (event.type === "browser_step") {
                        const { type: _t, ...step } = event;
                        void _t;
                        const browserSteps = [...(last.browserSteps ?? []), step];
                        next[next.length - 1] = { ...last, browserSteps };
                    }
                    else if (event.type === "attachment") {
                        const atts = [...(last.attachments ?? []), event];
                        next[next.length - 1] = { ...last, attachments: atts };
                    }
                    else if (event.type === "doc_updated") {
                        onDocUpdated();
                    }
                    else if (event.type === "error") {
                        next[next.length - 1] = { ...last, error: event.message, streaming: false };
                    }
                    else if (event.type === "done") {
                        next[next.length - 1] = { ...last, streaming: false };
                    }
                    return next;
                });
            }, controller.signal);
        }
        catch (err) {
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
        }
        finally {
            setSending(false);
            abortRef.current = null;
        }
    }
    const trimmed = draft.trim();
    const canSend = !sending && (trimmed.length > 0 || attachments.length > 0);
    return (_jsxs("section", { className: `chat-panel${dragActive ? " chat-drop-active" : ""}`, onDragOver: (e) => {
            e.preventDefault();
            setDragActive(true);
        }, onDragLeave: (e) => {
            if (e.currentTarget === e.target)
                setDragActive(false);
        }, onDrop: handleDrop, children: [_jsxs("div", { className: "chat-header", children: [_jsx("div", { className: "chat-title", children: chat.name }), chat.browser_enabled && _jsx("span", { className: "chat-browser-on", title: "Browser walkthrough enabled", children: "\uD83C\uDF10 walkthrough on" })] }), _jsx("div", { className: "chat-messages", ref: scrollerRef, children: messages.length === 0 ? (_jsxs("div", { className: "chat-empty", children: ["Start by describing the page. Attach screenshots or PDFs (\uD83D\uDCCE, paste, or drag & drop), or type ", _jsx("code", { children: "/browse" }), " to have the agent open and verify it live."] })) : (messages.map((m, i) => _jsx(MessageBubble, { message: m, onPreview: setPreview }, i))) }), _jsxs("div", { className: "composer", children: [attachments.length > 0 && (_jsx("div", { className: "attachment-chips", children: attachments.map((a) => (_jsxs("div", { className: "attachment-chip", title: `${a.file.name} · ${fmtSize(a.file.size)} — click to preview`, onClick: () => {
                                if (a.kind === "image" && a.previewUrl)
                                    setPreview({ url: a.previewUrl, name: a.file.name });
                                else if (a.previewUrl)
                                    window.open(a.previewUrl, "_blank");
                            }, children: [a.kind === "image" && a.previewUrl ? (_jsx("img", { src: a.previewUrl, alt: a.file.name })) : (_jsx("span", { className: "attachment-chip-icon", children: "\uD83D\uDCC4" })), _jsx("span", { className: "attachment-chip-name", children: a.file.name }), _jsx("button", { type: "button", className: "attachment-chip-remove", title: "Remove attachment", onClick: (e) => {
                                        e.stopPropagation();
                                        removeAttachment(a.id);
                                    }, children: "\u00D7" })] }, a.id))) })), _jsxs("div", { className: `composer-row${browseMode ? " browse-active" : ""}`, children: [_jsxs("div", { className: "composer-icons", children: [_jsx("button", { type: "button", className: "icon-btn", title: "Attach screenshots or PDFs", onClick: () => fileInputRef.current?.click(), children: "\uD83D\uDCCE" }), _jsx("button", { type: "button", className: `icon-btn${chat.browser_enabled ? " on" : ""}`, title: "Browser walkthrough settings (URL, login, notes)", onClick: () => setShowBrowserCfg(true), children: "\uD83C\uDF10" }), _jsx("input", { ref: fileInputRef, type: "file", accept: "image/*,application/pdf", multiple: true, className: "hidden-file", "aria-label": "Attach screenshots or PDFs", onChange: (e) => {
                                            if (e.target.files?.length)
                                                addFiles(e.target.files);
                                            e.target.value = "";
                                        } })] }), _jsxs("div", { className: "composer-input", children: [_jsx("div", { className: "input-highlight", ref: highlightRef, "aria-hidden": "true", children: renderHighlight(draft) }), _jsx("textarea", { className: "composer-textarea", placeholder: "Message the agent\u2026  \u00B7  /browse to open & verify the page", value: draft, onChange: (e) => setDraft(e.target.value), onPaste: handlePaste, onScroll: (e) => {
                                            if (highlightRef.current)
                                                highlightRef.current.scrollTop = e.currentTarget.scrollTop;
                                        }, onKeyDown: (e) => {
                                            if (e.key === "Enter" && !e.shiftKey) {
                                                e.preventDefault();
                                                send();
                                            }
                                        }, rows: 2 })] }), sending ? (_jsx("button", { type: "button", className: "composer-btn stop-btn", onClick: stop, title: "Stop generating", children: "\u25FC Stop" })) : (_jsx("button", { type: "button", className: "composer-btn send-btn", onClick: send, disabled: !canSend, title: "Send", children: "Send" }))] }), _jsx("div", { className: "composer-hint", children: sending
                            ? "Agent is responding — keep typing; press Stop to interrupt, then send."
                            : browseMode
                                ? "Browse mode: the agent will open & verify the page using your saved settings."
                                : "Enter to send · Shift+Enter for newline · 📎/paste/drag to attach · /browse to verify live" })] }), preview && (_jsx("div", { className: "attachment-preview-backdrop", onClick: () => setPreview(null), children: _jsxs("div", { className: "attachment-preview-modal", onClick: (e) => e.stopPropagation(), children: [_jsxs("div", { className: "attachment-preview-head", children: [_jsx("span", { children: preview.name }), _jsx("button", { type: "button", className: "attachment-preview-close", onClick: () => setPreview(null), children: "\u00D7" })] }), _jsx("img", { src: preview.url, alt: preview.name })] }) })), showBrowserCfg && (_jsx(BrowserConfigDialog, { chat: chat, onClose: () => setShowBrowserCfg(false), onSaved: onChatUpdated }))] }));
}
function renderHighlight(text) {
    const m = text.match(BROWSE_RE);
    if (m) {
        return (_jsxs(_Fragment, { children: [_jsx("span", { className: "cmd-token", children: "/browse" }), m[1], "​"] }));
    }
    return _jsxs(_Fragment, { children: [text, "​"] });
}
function MessageBubble({ message, onPreview, }) {
    const variant = message.role === "user" ? "user" : message.role === "system" ? "system" : "agent";
    const hasExtras = !!message.toolCalls?.length ||
        !!message.browserSteps?.length ||
        !!message.attachments?.length ||
        !!message.sentAttachments?.length;
    return (_jsxs("div", { className: `bubble ${variant}`, children: [message.role === "user" && message.browse ? _jsx("span", { className: "browse-tag", children: "/browse" }) : null, message.text ||
                (message.streaming && !hasExtras ? _jsx("span", { className: "bubble-stream-placeholder", children: "\u2026" }) : null), message.sentAttachments && message.sentAttachments.length > 0 ? (_jsx("div", { className: "sent-attachments", children: message.sentAttachments.map((a, i) => a.kind === "image" && a.previewUrl ? (_jsx("img", { className: "sent-attachment-thumb", src: a.previewUrl, alt: a.name, title: `${a.name} — click to preview`, onClick: () => onPreview({ url: a.previewUrl, name: a.name }) }, i)) : (_jsxs("span", { className: "attachment-pill", title: a.name, children: ["\uD83D\uDCC4 ", a.name] }, i))) })) : null, message.toolCalls?.map((tc, i) => (_jsxs("div", { className: "tool-call", children: [_jsxs("span", { className: "tool-call-name", children: ["\u2192 ", tc.name] }), tc.name === "update_document_section" && tc.args.section_name ? (_jsxs("span", { children: [" (", String(tc.args.section_name), ")"] })) : null, tc.name === "browser_open" && tc.args.url ? _jsxs("span", { children: [" (", String(tc.args.url), ")"] }) : null, (tc.name === "browser_click" || tc.name === "browser_fill") && tc.args.target ? (_jsxs("span", { children: [" (", String(tc.args.target), ")"] })) : null] }, i))), message.browserSteps?.map((step, i) => (_jsxs("div", { className: "browser-step", children: [_jsx("div", { className: "browser-step-action", children: step.action }), _jsxs("div", { className: "browser-step-meta", children: [_jsx("span", { children: step.title || "(untitled)" }), _jsx("span", { className: "browser-step-url", children: step.url })] }), step.screenshot_url ? (_jsx("img", { className: "browser-step-img", src: step.screenshot_url, alt: "Browser screenshot" })) : null, step.validation_messages.length > 0 ? (_jsxs("div", { className: "browser-step-validation", children: [_jsx("b", { children: "Validation:" }), " ", step.validation_messages.join(" · ")] })) : null, step.notes ? _jsxs("div", { className: "browser-step-error", children: ["\u26A0 ", step.notes] }) : null] }, i))), message.attachments?.map((att, i) => att.kind === "image" ? (_jsx("div", { className: "upload-preview", children: att.error ? (_jsxs("div", { className: "bubble-error", children: ["Could not annotate ", att.name, ": ", att.error] })) : (_jsxs(_Fragment, { children: [att.annotated_url ? (_jsx("img", { src: att.annotated_url, alt: "Annotated screenshot", onClick: () => onPreview({ url: att.annotated_url, name: att.name }) })) : null, att.page_summary ? _jsx("div", { className: "upload-summary", children: att.page_summary }) : null, att.elements && att.elements.length > 0 ? (_jsxs("ol", { className: "upload-elements", children: [att.elements.slice(0, 8).map((el) => (_jsxs("li", { children: [_jsx("b", { children: el.label || `(unlabeled ${el.element_type})` }), _jsxs("span", { className: "upload-element-kind", children: [" ", "\u00B7 ", el.element_type, el.is_repeated_group && (el.instance_count ?? 1) > 1
                                                    ? ` (repeated ×${el.instance_count})`
                                                    : ""] }), _jsx("div", { className: "upload-element-action", children: el.inferred_action })] }, el.index))), (att.element_count ?? att.elements.length) > 8 ? (_jsxs("li", { className: "upload-elements-more", children: ["+ ", (att.element_count ?? att.elements.length) - 8, " more in the canvas table"] })) : null] })) : null] })) }, i)) : (_jsxs("a", { className: "attachment-pill attachment-pill-link", href: att.file_url, target: "_blank", rel: "noreferrer", children: ["\uD83D\uDCC4 ", att.name, " \u2014 linked in document"] }, i))), message.interrupted ? _jsx("div", { className: "bubble-interrupted", children: "\u25A0 interrupted" }) : null, message.error ? _jsx("div", { className: "bubble-error", children: message.error }) : null] }));
}

import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { api, streamMessage } from "../api/client";
export function ChatPanel({ chat, onToggleBrowser, onDocUpdated }) {
    const [messages, setMessages] = useState([]);
    const [draft, setDraft] = useState("");
    const [sending, setSending] = useState(false);
    const [uploading, setUploading] = useState(false);
    const scrollerRef = useRef(null);
    const abortRef = useRef(null);
    const fileInputRef = useRef(null);
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
        if (el)
            el.scrollTop = el.scrollHeight;
    }, [messages]);
    async function send() {
        const text = draft.trim();
        if (!text || sending)
            return;
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
            await streamMessage(chat.id, text, (event) => {
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
            const msg = err instanceof Error ? err.message : String(err);
            setMessages((prev) => {
                const next = [...prev];
                const last = next[next.length - 1];
                if (last && last.role === "agent") {
                    next[next.length - 1] = { ...last, error: msg, streaming: false };
                }
                return next;
            });
        }
        finally {
            setSending(false);
            abortRef.current = null;
        }
    }
    async function handleFile(file) {
        if (uploading || sending)
            return;
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
        }
        catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            setMessages((prev) => {
                const next = [...prev];
                const last = next[next.length - 1];
                if (last && last.role === "agent") {
                    next[next.length - 1] = { ...last, error: msg, streaming: false };
                }
                return next;
            });
        }
        finally {
            setUploading(false);
        }
    }
    return (_jsxs("section", { className: "chat-panel", children: [_jsxs("div", { className: "chat-header", children: [_jsx("div", { className: "chat-title", children: chat.name }), _jsx("div", { className: "chat-controls", children: _jsxs("label", { className: "toggle", title: "Per-chat browser walkthrough toggle", children: [_jsx("input", { type: "checkbox", checked: chat.browser_enabled, onChange: (e) => onToggleBrowser(e.target.checked) }), _jsx("span", { children: "Browser walkthrough" })] }) })] }), _jsx("div", { className: "chat-messages", ref: scrollerRef, children: messages.length === 0 ? (_jsx("div", { className: "chat-empty", children: "Start by describing the product or feature. The agent will interview you and write the guide on the right." })) : (messages.map((m, i) => _jsx(MessageBubble, { message: m }, i))) }), _jsxs("div", { className: "chat-input-wrap", children: [_jsxs("div", { className: "chat-input-row", children: [_jsx("button", { type: "button", className: "attach-btn", title: "Attach a screenshot for annotation", onClick: () => fileInputRef.current?.click(), disabled: uploading || sending, children: "\uD83D\uDCCE" }), _jsx("input", { ref: fileInputRef, type: "file", accept: "image/*", className: "hidden-file", "aria-label": "Attach screenshot for annotation", title: "Attach screenshot for annotation", onChange: (e) => {
                                    const f = e.target.files?.[0];
                                    if (f)
                                        handleFile(f);
                                    e.target.value = "";
                                } }), _jsx("textarea", { className: "chat-input", placeholder: sending
                                    ? "Agent is responding…"
                                    : uploading
                                        ? "Annotating screenshot…"
                                        : "Describe this page, answer the agent, or attach a screenshot…", value: draft, onChange: (e) => setDraft(e.target.value), disabled: sending || uploading, onKeyDown: (e) => {
                                    if (e.key === "Enter" && !e.shiftKey) {
                                        e.preventDefault();
                                        send();
                                    }
                                }, rows: 2 })] }), _jsx("div", { className: "chat-input-hint", children: "Enter to send \u00B7 Shift+Enter for newline \u00B7 \uD83D\uDCCE to attach a page screenshot (any image, max 20 MB)" })] })] }));
}
function MessageBubble({ message }) {
    const variant = message.role === "user" ? "user" : message.role === "system" ? "system" : "agent";
    return (_jsxs("div", { className: `bubble ${variant}`, children: [message.text ||
                (message.streaming &&
                    !message.toolCalls?.length &&
                    !message.browserSteps?.length &&
                    !message.upload ? (_jsx("span", { className: "bubble-stream-placeholder", children: "\u2026" })) : null), message.toolCalls?.map((tc, i) => (_jsxs("div", { className: "tool-call", children: [_jsxs("span", { className: "tool-call-name", children: ["\u2192 ", tc.name] }), tc.name === "update_document_section" && tc.args.section_name ? (_jsxs("span", { children: [" (", String(tc.args.section_name), ")"] })) : null, tc.name === "browser_open" && tc.args.url ? (_jsxs("span", { children: [" (", String(tc.args.url), ")"] })) : null, (tc.name === "browser_click" || tc.name === "browser_fill") && tc.args.target ? (_jsxs("span", { children: [" (", String(tc.args.target), ")"] })) : null] }, i))), message.browserSteps?.map((step, i) => (_jsxs("div", { className: "browser-step", children: [_jsx("div", { className: "browser-step-action", children: step.action }), _jsxs("div", { className: "browser-step-meta", children: [_jsx("span", { children: step.title || "(untitled)" }), _jsx("span", { className: "browser-step-url", children: step.url })] }), step.screenshot_url ? (_jsx("img", { className: "browser-step-img", src: step.screenshot_url, alt: "Browser screenshot" })) : null, step.validation_messages.length > 0 ? (_jsxs("div", { className: "browser-step-validation", children: [_jsx("b", { children: "Validation:" }), " ", step.validation_messages.join(" · ")] })) : null, step.notes ? _jsxs("div", { className: "browser-step-error", children: ["\u26A0 ", step.notes] }) : null] }, i))), message.upload ? (_jsxs("div", { className: "upload-preview", children: [_jsx("img", { src: message.upload.annotated_url, alt: "Annotated screenshot" }), _jsx("div", { className: "upload-summary", children: message.upload.page_summary }), message.upload.elements.length > 0 ? (_jsxs("ol", { className: "upload-elements", children: [message.upload.elements.slice(0, 8).map((el) => (_jsxs("li", { children: [_jsx("b", { children: el.label || `(unlabeled ${el.element_type})` }), _jsxs("span", { className: "upload-element-kind", children: [" \u00B7 ", el.element_type] }), _jsx("div", { className: "upload-element-action", children: el.inferred_action })] }, el.index))), message.upload.elements.length > 8 ? (_jsxs("li", { className: "upload-elements-more", children: ["+ ", message.upload.elements.length - 8, " more in the canvas table"] })) : null] })) : null] })) : null, message.error ? _jsx("div", { className: "bubble-error", children: message.error }) : null] }));
}

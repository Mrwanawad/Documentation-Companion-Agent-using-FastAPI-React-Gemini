import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { api } from "../api/client";
export function BrowserConfigDialog({ chat, onClose, onSaved }) {
    const [url, setUrl] = useState(chat.browser_url ?? "");
    const [email, setEmail] = useState(chat.browser_email ?? "");
    const [password, setPassword] = useState(chat.browser_password ?? "");
    const [notes, setNotes] = useState(chat.browser_notes ?? "");
    const [enabled, setEnabled] = useState(chat.browser_enabled);
    const [busy, setBusy] = useState(false);
    async function save() {
        if (busy)
            return;
        setBusy(true);
        try {
            const updated = await api.updateChat(chat.id, {
                browser_enabled: enabled,
                browser_url: url.trim(),
                browser_email: email.trim(),
                browser_password: password,
                browser_notes: notes.trim(),
            });
            onSaved(updated);
            onClose();
        }
        finally {
            setBusy(false);
        }
    }
    return (_jsx("div", { className: "dialog-backdrop", onClick: onClose, children: _jsxs("div", { className: "dialog", onClick: (e) => e.stopPropagation(), children: [_jsx("h2", { children: "Browser walkthrough" }), _jsx("p", { className: "dialog-sub", children: "The agent can open this page and verify it. Credentials are saved locally for this chat so it can log in without asking." }), _jsxs("div", { className: "field", children: [_jsx("label", { htmlFor: "bw-url", children: "Page URL" }), _jsx("input", { id: "bw-url", type: "url", placeholder: "https://app.example.com/login", value: url, onChange: (e) => setUrl(e.target.value), autoFocus: true })] }), _jsxs("div", { className: "field-row", children: [_jsxs("div", { className: "field", children: [_jsxs("label", { htmlFor: "bw-email", children: ["Email / username ", _jsx("span", { className: "opt", children: "(optional)" })] }), _jsx("input", { id: "bw-email", type: "text", placeholder: "you@example.com", value: email, onChange: (e) => setEmail(e.target.value), autoComplete: "off" })] }), _jsxs("div", { className: "field", children: [_jsxs("label", { htmlFor: "bw-pass", children: ["Password ", _jsx("span", { className: "opt", children: "(optional)" })] }), _jsx("input", { id: "bw-pass", type: "password", placeholder: "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022", value: password, onChange: (e) => setPassword(e.target.value), autoComplete: "new-password" })] })] }), _jsxs("div", { className: "field", children: [_jsxs("label", { htmlFor: "bw-notes", children: ["Notes ", _jsx("span", { className: "opt", children: "(optional)" })] }), _jsx("textarea", { id: "bw-notes", placeholder: "Anything the agent should know \u2014 e.g. 'use the Staging tenant', '2FA code will be texted'\u2026", value: notes, onChange: (e) => setNotes(e.target.value), rows: 3 })] }), _jsxs("div", { className: "field", children: [_jsxs("label", { className: "toggle", children: [_jsx("input", { type: "checkbox", checked: enabled, onChange: (e) => setEnabled(e.target.checked) }), _jsx("span", { className: "toggle-label", children: "Enable browser walkthrough for this chat" })] }), _jsxs("div", { className: "field-hint", children: ["When on, the agent may drive a real browser. You can also trigger a one-off walkthrough by typing ", _jsx("code", { children: "/browse" }), " in the chat."] })] }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "button", className: "btn btn-ghost", onClick: onClose, disabled: busy, children: "Cancel" }), _jsx("button", { type: "button", className: "btn btn-primary", onClick: save, disabled: busy, children: busy ? "Saving…" : "Save" })] })] }) }));
}

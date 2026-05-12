import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
export function NewChatDialog({ onCancel, onCreate }) {
    const [name, setName] = useState("");
    const [browserEnabled, setBrowserEnabled] = useState(true);
    const [busy, setBusy] = useState(false);
    const trimmed = name.trim();
    async function submit() {
        if (!trimmed || busy)
            return;
        setBusy(true);
        try {
            await onCreate(trimmed, browserEnabled);
        }
        finally {
            setBusy(false);
        }
    }
    return (_jsx("div", { className: "dialog-backdrop", onClick: onCancel, children: _jsxs("div", { className: "dialog", onClick: (e) => e.stopPropagation(), children: [_jsx("h2", { children: "New page guide" }), _jsxs("div", { className: "field", children: [_jsx("label", { htmlFor: "chat-name", children: "Page name" }), _jsx("input", { id: "chat-name", type: "text", placeholder: "e.g. Boards list page \u00B7 Create invoice form", value: name, onChange: (e) => setName(e.target.value), onKeyDown: (e) => {
                                if (e.key === "Enter")
                                    submit();
                                if (e.key === "Escape")
                                    onCancel();
                            }, autoFocus: true }), _jsx("div", { className: "field-hint", children: "One page/screen of your SaaS or ERP. The agent will interview you and write a guide for that single page." })] }), _jsxs("div", { className: "field", children: [_jsxs("label", { className: "toggle", children: [_jsx("input", { type: "checkbox", checked: browserEnabled, onChange: (e) => setBrowserEnabled(e.target.checked) }), _jsx("span", { className: "toggle-label", children: "Enable browser walkthrough" })] }), _jsx("div", { className: "field-hint", children: "When off, the agent skips browser evidence and that section is omitted from the guide." })] }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "button", className: "btn btn-ghost", onClick: onCancel, disabled: busy, children: "Cancel" }), _jsx("button", { type: "button", className: "btn btn-primary", onClick: submit, disabled: !trimmed || busy, children: busy ? "Creating…" : "Create" })] })] }) }));
}

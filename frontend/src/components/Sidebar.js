import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { StatusBadge } from "./StatusBadge";
function fmtDate(iso) {
    const d = new Date(iso);
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) {
        return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
export function Sidebar({ chats, activeId, collapsed, onToggleCollapse, onSelect, onDelete, onNew }) {
    if (collapsed) {
        return (_jsxs("aside", { className: "sidebar sidebar-rail", children: [_jsx("button", { type: "button", className: "rail-btn", title: "Expand sidebar", onClick: onToggleCollapse, children: "\u203A" }), _jsx("button", { type: "button", className: "rail-btn rail-new", title: "New chat", onClick: onNew, children: "+" })] }));
    }
    return (_jsxs("aside", { className: "sidebar", children: [_jsxs("div", { className: "sidebar-header", children: [_jsxs("div", { className: "brand", children: [_jsx("span", { className: "brand-mark", children: "<j>" }), _jsx("span", { children: "Coject Docs" })] }), _jsxs("div", { className: "sidebar-header-actions", children: [_jsx("button", { type: "button", className: "new-chat-btn", onClick: onNew, children: "+ New" }), _jsx("button", { type: "button", className: "collapse-btn", title: "Collapse sidebar", onClick: onToggleCollapse, children: "\u00AB" })] })] }), _jsx("div", { className: "sidebar-list", children: chats.length === 0 ? (_jsxs("div", { className: "sidebar-empty", children: ["No chats yet. Click ", _jsx("b", { children: "+ New" }), " to start."] })) : (chats.map((c) => (_jsxs("div", { className: `chat-row${c.id === activeId ? " active" : ""}`, onClick: () => onSelect(c.id), children: [_jsxs("div", { className: "chat-row-top", children: [_jsx("div", { className: "chat-name", title: c.name, children: c.name }), _jsx("button", { type: "button", className: "chat-delete", title: "Delete chat + document", onClick: (e) => {
                                        e.stopPropagation();
                                        onDelete(c);
                                    }, children: "\u00D7" })] }), _jsxs("div", { className: "chat-row-bottom", children: [_jsx(StatusBadge, { status: c.status }), _jsx("span", { children: fmtDate(c.updated_at) })] })] }, c.id)))) })] }));
}

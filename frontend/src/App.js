import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { ChatPanel } from "./components/ChatPanel";
import { CanvasPanel } from "./components/CanvasPanel";
import { NewChatDialog } from "./components/NewChatDialog";
import { api } from "./api/client";
function loadBool(key, fallback) {
    const v = localStorage.getItem(key);
    return v === null ? fallback : v === "1";
}
function loadNum(key, fallback) {
    const v = Number(localStorage.getItem(key));
    return Number.isFinite(v) && v > 0 ? v : fallback;
}
export default function App() {
    const [chats, setChats] = useState([]);
    const [activeId, setActiveId] = useState(null);
    const [showNew, setShowNew] = useState(false);
    const [docVersion, setDocVersion] = useState(0);
    const [sidebarCollapsed, setSidebarCollapsed] = useState(() => loadBool("ui.sidebarCollapsed", false));
    const [canvasCollapsed, setCanvasCollapsed] = useState(() => loadBool("ui.canvasCollapsed", false));
    const [canvasPct, setCanvasPct] = useState(() => loadNum("ui.canvasPct", 50));
    const workspaceRef = useRef(null);
    const dragging = useRef(false);
    useEffect(() => localStorage.setItem("ui.sidebarCollapsed", sidebarCollapsed ? "1" : "0"), [sidebarCollapsed]);
    useEffect(() => localStorage.setItem("ui.canvasCollapsed", canvasCollapsed ? "1" : "0"), [canvasCollapsed]);
    useEffect(() => localStorage.setItem("ui.canvasPct", String(Math.round(canvasPct))), [canvasPct]);
    async function refresh() {
        const list = await api.listChats();
        setChats(list);
        if (activeId && !list.find((c) => c.id === activeId))
            setActiveId(null);
    }
    useEffect(() => {
        refresh();
    }, []);
    function startDrag(e) {
        e.preventDefault();
        dragging.current = true;
        document.body.classList.add("dragging-col");
        const onMove = (ev) => {
            if (!dragging.current || !workspaceRef.current)
                return;
            const rect = workspaceRef.current.getBoundingClientRect();
            const pct = ((rect.right - ev.clientX) / rect.width) * 100;
            setCanvasPct(Math.min(80, Math.max(20, pct)));
        };
        const onUp = () => {
            dragging.current = false;
            document.body.classList.remove("dragging-col");
            window.removeEventListener("mousemove", onMove);
            window.removeEventListener("mouseup", onUp);
        };
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
    }
    async function handleCreate(name, browserEnabled) {
        const created = await api.createChat(name, browserEnabled);
        setShowNew(false);
        await refresh();
        setActiveId(created.id);
    }
    async function handleDelete(chat) {
        const ok = window.confirm(`Delete "${chat.name}"?\n\nThis removes the chat AND its document and all assets.`);
        if (!ok)
            return;
        await api.deleteChat(chat.id);
        if (activeId === chat.id)
            setActiveId(null);
        await refresh();
    }
    function patchActive(updated) {
        setChats((cs) => cs.map((c) => (c.id === updated.id ? updated : c)));
    }
    const active = chats.find((c) => c.id === activeId) ?? null;
    return (_jsxs("div", { className: `app${sidebarCollapsed ? " sidebar-collapsed" : ""}`, children: [_jsx(Sidebar, { chats: chats, activeId: activeId, collapsed: sidebarCollapsed, onToggleCollapse: () => setSidebarCollapsed((v) => !v), onSelect: setActiveId, onDelete: handleDelete, onNew: () => setShowNew(true) }), _jsx("main", { className: "workspace", ref: workspaceRef, children: active === null ? (_jsxs("div", { className: "empty-workspace empty-workspace-wrap", children: [_jsxs("h1", { children: ["Coject ", _jsx("span", { className: "empty-accent", children: "Documentation Companion" })] }), _jsx("p", { children: "Create a new chat to start documenting a product or feature. The agent will interview you and write a reviewable Markdown guide." }), _jsx("button", { type: "button", className: "btn btn-primary", onClick: () => setShowNew(true), children: "+ New chat" })] })) : (_jsxs(_Fragment, { children: [_jsx("div", { className: "chat-pane", children: _jsx(ChatPanel, { chat: active, onChatUpdated: patchActive, onDocUpdated: () => setDocVersion((v) => v + 1) }) }), canvasCollapsed ? (_jsx("button", { type: "button", className: "canvas-reopen", title: "Show document", onClick: () => setCanvasCollapsed(false), children: "\u2039 Document" })) : (_jsxs(_Fragment, { children: [_jsx("div", { className: "col-divider", onMouseDown: startDrag, title: "Drag to resize" }), _jsx("div", { className: "canvas-pane", style: { flex: `0 0 ${canvasPct}%` }, children: _jsx(CanvasPanel, { chatId: active.id, version: active.current_version, readonly: active.status === "approved", refreshSignal: docVersion, onCollapse: () => setCanvasCollapsed(true) }, active.id) })] }))] })) }), showNew && _jsx(NewChatDialog, { onCancel: () => setShowNew(false), onCreate: handleCreate })] }));
}

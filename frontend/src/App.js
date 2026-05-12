import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { ChatPanel } from "./components/ChatPanel";
import { CanvasPanel } from "./components/CanvasPanel";
import { NewChatDialog } from "./components/NewChatDialog";
import { api } from "./api/client";
export default function App() {
    const [chats, setChats] = useState([]);
    const [activeId, setActiveId] = useState(null);
    const [showNew, setShowNew] = useState(false);
    const [docVersion, setDocVersion] = useState(0);
    async function refresh() {
        const list = await api.listChats();
        setChats(list);
        if (activeId && !list.find((c) => c.id === activeId)) {
            setActiveId(null);
        }
    }
    useEffect(() => {
        refresh();
    }, []);
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
    async function handleToggleBrowser(enabled) {
        if (!activeId)
            return;
        const updated = await api.updateChat(activeId, { browser_enabled: enabled });
        setChats((cs) => cs.map((c) => (c.id === updated.id ? updated : c)));
    }
    const active = chats.find((c) => c.id === activeId) ?? null;
    return (_jsxs("div", { className: "app", children: [_jsx(Sidebar, { chats: chats, activeId: activeId, onSelect: setActiveId, onDelete: handleDelete, onNew: () => setShowNew(true) }), active === null ? (_jsxs("div", { className: "empty-workspace empty-workspace-wrap", children: [_jsxs("h1", { children: ["Coject ", _jsx("span", { className: "empty-accent", children: "Documentation Companion" })] }), _jsx("p", { children: "Create a new chat to start documenting a product or feature. The agent will interview you and write a reviewable Markdown guide." }), _jsx("button", { type: "button", className: "btn btn-primary", onClick: () => setShowNew(true), children: "+ New chat" })] })) : (_jsxs(_Fragment, { children: [_jsx(ChatPanel, { chat: active, onToggleBrowser: handleToggleBrowser, onDocUpdated: () => setDocVersion((v) => v + 1) }), _jsx(CanvasPanel, { chatId: active.id, version: active.current_version, readonly: active.status === "approved", refreshSignal: docVersion }, active.id)] })), showNew && (_jsx(NewChatDialog, { onCancel: () => setShowNew(false), onCreate: handleCreate }))] }));
}

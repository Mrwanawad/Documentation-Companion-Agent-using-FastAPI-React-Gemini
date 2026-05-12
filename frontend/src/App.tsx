import { useEffect, useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { ChatPanel } from "./components/ChatPanel";
import { CanvasPanel } from "./components/CanvasPanel";
import { NewChatDialog } from "./components/NewChatDialog";
import { api } from "./api/client";
import type { ChatMeta } from "./types";

export default function App() {
  const [chats, setChats] = useState<ChatMeta[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
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

  async function handleCreate(name: string, browserEnabled: boolean) {
    const created = await api.createChat(name, browserEnabled);
    setShowNew(false);
    await refresh();
    setActiveId(created.id);
  }

  async function handleDelete(chat: ChatMeta) {
    const ok = window.confirm(
      `Delete "${chat.name}"?\n\nThis removes the chat AND its document and all assets.`,
    );
    if (!ok) return;
    await api.deleteChat(chat.id);
    if (activeId === chat.id) setActiveId(null);
    await refresh();
  }

  async function handleToggleBrowser(enabled: boolean) {
    if (!activeId) return;
    const updated = await api.updateChat(activeId, { browser_enabled: enabled });
    setChats((cs) => cs.map((c) => (c.id === updated.id ? updated : c)));
  }

  const active = chats.find((c) => c.id === activeId) ?? null;

  return (
    <div className="app">
      <Sidebar
        chats={chats}
        activeId={activeId}
        onSelect={setActiveId}
        onDelete={handleDelete}
        onNew={() => setShowNew(true)}
      />

      {active === null ? (
        <div className="empty-workspace empty-workspace-wrap">
          <h1>
            Coject <span className="empty-accent">Documentation Companion</span>
          </h1>
          <p>
            Create a new chat to start documenting a product or feature. The agent will interview you and write a reviewable Markdown guide.
          </p>
          <button type="button" className="btn btn-primary" onClick={() => setShowNew(true)}>
            + New chat
          </button>
        </div>
      ) : (
        <>
          <ChatPanel
            chat={active}
            onToggleBrowser={handleToggleBrowser}
            onDocUpdated={() => setDocVersion((v) => v + 1)}
          />
          <CanvasPanel
            key={active.id}
            chatId={active.id}
            version={active.current_version}
            readonly={active.status === "approved"}
            refreshSignal={docVersion}
          />
        </>
      )}

      {showNew && (
        <NewChatDialog
          onCancel={() => setShowNew(false)}
          onCreate={handleCreate}
        />
      )}
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { ChatPanel } from "./components/ChatPanel";
import { CanvasPanel } from "./components/CanvasPanel";
import { NewChatDialog } from "./components/NewChatDialog";
import { api } from "./api/client";
import type { ChatMeta, DocLanguage } from "./types";

function loadBool(key: string, fallback: boolean): boolean {
  const v = localStorage.getItem(key);
  return v === null ? fallback : v === "1";
}
function loadNum(key: string, fallback: number): number {
  const v = Number(localStorage.getItem(key));
  return Number.isFinite(v) && v > 0 ? v : fallback;
}

export default function App() {
  const [chats, setChats] = useState<ChatMeta[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [docVersion, setDocVersion] = useState(0);

  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => loadBool("ui.sidebarCollapsed", false));
  const [canvasCollapsed, setCanvasCollapsed] = useState(() => loadBool("ui.canvasCollapsed", false));
  const [canvasPct, setCanvasPct] = useState(() => loadNum("ui.canvasPct", 50));
  const workspaceRef = useRef<HTMLDivElement | null>(null);
  const dragging = useRef(false);

  useEffect(() => localStorage.setItem("ui.sidebarCollapsed", sidebarCollapsed ? "1" : "0"), [sidebarCollapsed]);
  useEffect(() => localStorage.setItem("ui.canvasCollapsed", canvasCollapsed ? "1" : "0"), [canvasCollapsed]);
  useEffect(() => localStorage.setItem("ui.canvasPct", String(Math.round(canvasPct))), [canvasPct]);

  async function refresh() {
    const list = await api.listChats();
    setChats(list);
    if (activeId && !list.find((c) => c.id === activeId)) setActiveId(null);
  }

  useEffect(() => {
    refresh();
  }, []);

  function startDrag(e: React.MouseEvent) {
    e.preventDefault();
    dragging.current = true;
    document.body.classList.add("dragging-col");
    const onMove = (ev: MouseEvent) => {
      if (!dragging.current || !workspaceRef.current) return;
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

  async function handleCreate(name: string, browserEnabled: boolean, language: DocLanguage) {
    const created = await api.createChat(name, browserEnabled, language);
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

  function patchActive(updated: ChatMeta) {
    setChats((cs) => cs.map((c) => (c.id === updated.id ? updated : c)));
  }

  const active = chats.find((c) => c.id === activeId) ?? null;

  return (
    <div className={`app${sidebarCollapsed ? " sidebar-collapsed" : ""}`}>
      <Sidebar
        chats={chats}
        activeId={activeId}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
        onSelect={setActiveId}
        onDelete={handleDelete}
        onNew={() => setShowNew(true)}
      />

      <main className="workspace" ref={workspaceRef}>
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
            <div className="chat-pane">
              <ChatPanel
                chat={active}
                onChatUpdated={patchActive}
                onDocUpdated={() => setDocVersion((v) => v + 1)}
              />
            </div>

            {canvasCollapsed ? (
              <button
                type="button"
                className="canvas-reopen"
                title="Show document"
                onClick={() => setCanvasCollapsed(false)}
              >
                ‹ Document
              </button>
            ) : (
              <>
                <div className="col-divider" onMouseDown={startDrag} title="Drag to resize" />
                <div className="canvas-pane" style={{ flex: `0 0 ${canvasPct}%` }}>
                  <CanvasPanel
                    key={active.id}
                    chatId={active.id}
                    version={active.current_version}
                    readonly={active.status === "approved"}
                    refreshSignal={docVersion}
                    onCollapse={() => setCanvasCollapsed(true)}
                  />
                </div>
              </>
            )}
          </>
        )}
      </main>

      {showNew && <NewChatDialog onCancel={() => setShowNew(false)} onCreate={handleCreate} />}
    </div>
  );
}

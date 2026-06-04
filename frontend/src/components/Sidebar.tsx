import type { ChatMeta } from "../types";
import { StatusBadge } from "./StatusBadge";

interface Props {
  chats: ChatMeta[];
  activeId: string | null;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onSelect: (id: string) => void;
  onDelete: (chat: ChatMeta) => void;
  onNew: () => void;
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) {
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function Sidebar({ chats, activeId, collapsed, onToggleCollapse, onSelect, onDelete, onNew }: Props) {
  if (collapsed) {
    return (
      <aside className="sidebar sidebar-rail">
        <button type="button" className="rail-btn" title="Expand sidebar" onClick={onToggleCollapse}>
          ›
        </button>
        <button type="button" className="rail-btn rail-new" title="New chat" onClick={onNew}>
          +
        </button>
      </aside>
    );
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="brand">
          <span className="brand-mark">&lt;j&gt;</span>
          <span>Coject Docs</span>
        </div>
        <div className="sidebar-header-actions">
          <button type="button" className="new-chat-btn" onClick={onNew}>+ New</button>
          <button type="button" className="collapse-btn" title="Collapse sidebar" onClick={onToggleCollapse}>
            «
          </button>
        </div>
      </div>
      <div className="sidebar-list">
        {chats.length === 0 ? (
          <div className="sidebar-empty">No chats yet. Click <b>+ New</b> to start.</div>
        ) : (
          chats.map((c) => (
            <div
              key={c.id}
              className={`chat-row${c.id === activeId ? " active" : ""}`}
              onClick={() => onSelect(c.id)}
            >
              <div className="chat-row-top">
                <div className="chat-name" title={c.name}>{c.name}</div>
                <button
                  type="button"
                  className="chat-delete"
                  title="Delete chat + document"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(c);
                  }}
                >
                  ×
                </button>
              </div>
              <div className="chat-row-bottom">
                <StatusBadge status={c.status} />
                <span>{fmtDate(c.updated_at)}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}

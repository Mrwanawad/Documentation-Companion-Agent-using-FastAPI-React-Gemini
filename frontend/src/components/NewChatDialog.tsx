import { useState } from "react";

interface Props {
  onCancel: () => void;
  onCreate: (name: string, browserEnabled: boolean) => Promise<void>;
}

export function NewChatDialog({ onCancel, onCreate }: Props) {
  const [name, setName] = useState("");
  const [browserEnabled, setBrowserEnabled] = useState(true);
  const [busy, setBusy] = useState(false);

  const trimmed = name.trim();

  async function submit() {
    if (!trimmed || busy) return;
    setBusy(true);
    try {
      await onCreate(trimmed, browserEnabled);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="dialog-backdrop" onClick={onCancel}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <h2>New page guide</h2>

        <div className="field">
          <label htmlFor="chat-name">Page name</label>
          <input
            id="chat-name"
            type="text"
            placeholder="e.g. Boards list page · Create invoice form"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
              if (e.key === "Escape") onCancel();
            }}
            autoFocus
          />
          <div className="field-hint">
            One page/screen of your SaaS or ERP. The agent will interview you and write a guide for that single page.
          </div>
        </div>

        <div className="field">
          <label className="toggle">
            <input
              type="checkbox"
              checked={browserEnabled}
              onChange={(e) => setBrowserEnabled(e.target.checked)}
            />
            <span className="toggle-label">Enable browser walkthrough</span>
          </label>
          <div className="field-hint">
            When off, the agent skips browser evidence and that section is omitted from the guide.
          </div>
        </div>

        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" onClick={submit} disabled={!trimmed || busy}>
            {busy ? "Creating…" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}

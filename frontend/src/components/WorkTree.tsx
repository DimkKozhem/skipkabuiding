import { useState } from "react";
import type { ConstructionWorkNode, ConstructionWorksResponse } from "../types";

function WorkNode({
  node,
  mode,
  selectedId,
  onSelect,
  depth = 0,
}: {
  node: ConstructionWorkNode;
  mode: "preview" | "pick";
  selectedId?: string | null;
  onSelect?: (node: ConstructionWorkNode) => void;
  depth?: number;
}) {
  const children = node.children || [];
  const [open, setOpen] = useState(depth < 1 || children.length === 0);
  const selected = selectedId === node.id;
  const pickable = mode === "pick";

  return (
    <li className={`work-tree-node depth-${Math.min(depth, 3)}${selected ? " is-selected" : ""}`}>
      <div className="work-tree-row">
        {children.length > 0 ? (
          <button
            type="button"
            className="work-tree-toggle"
            aria-expanded={open}
            onClick={() => setOpen(value => !value)}
            title={open ? "Свернуть" : "Развернуть"}
          >
            {open ? "▾" : "▸"}
          </button>
        ) : (
          <span className="work-tree-toggle placeholder" />
        )}
        {pickable ? (
          <button
            type="button"
            className={`work-tree-label pickable${selected ? " selected" : ""}`}
            onClick={() => onSelect?.(node)}
          >
            <span>{node.name}</span>
            {node.code ? <span className="work-tree-code">{node.code}</span> : null}
          </button>
        ) : (
          <span className="work-tree-label">
            <span>{node.name}</span>
            {node.code ? <span className="work-tree-code">{node.code}</span> : null}
          </span>
        )}
      </div>
      {open && children.length > 0 && (
        <ul className="work-tree-list nested">
          {children.map(child => (
            <WorkNode
              key={child.id}
              node={child}
              mode={mode}
              selectedId={selectedId}
              onSelect={onSelect}
              depth={depth + 1}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

export function WorkTree({
  data,
  mode = "preview",
  selectedId,
  onSelect,
}: {
  data: ConstructionWorksResponse | null;
  mode?: "preview" | "pick";
  selectedId?: string | null;
  onSelect?: (node: ConstructionWorkNode) => void;
}) {
  if (!data) return null;
  if (!data.groups.length) {
    return <p className="muted">Для этого вида строительства работы в справочнике не найдены.</p>;
  }
  return (
    <div className="work-tree">
      {data.groups.map(group => (
        <section key={group.id} className="work-tree-group">
          <h3>{group.name}</h3>
          <ul className="work-tree-list">
            {group.works.map(work => (
              <WorkNode
                key={work.id}
                node={work}
                mode={mode}
                selectedId={selectedId}
                onSelect={onSelect}
              />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

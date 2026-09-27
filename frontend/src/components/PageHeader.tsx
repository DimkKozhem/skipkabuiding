import type { ReactNode } from "react";

export function PageHeader({
  title,
  lead,
  extra,
}: {
  title: string;
  lead?: string;
  extra?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {lead ? <p className="page-lead">{lead}</p> : null}
      </div>
      {extra ? <div className="page-header-extra">{extra}</div> : null}
    </div>
  );
}

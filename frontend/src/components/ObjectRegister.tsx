import type { ZoneDash } from "../types";
import { ZoneCard } from "./ZoneCard";

/** Один и тот же кадр карточки в обеих секциях витрины. */
export function ObjectRegister({ zones }: { zones: ZoneDash[]; feature?: boolean }) {
  return (
    <div className="vitrine-list" role="list">
      {zones.map(zone => (
        <div key={zone.code} role="listitem">
          <ZoneCard zone={zone} href={`/objects/${zone.code}`} />
        </div>
      ))}
    </div>
  );
}

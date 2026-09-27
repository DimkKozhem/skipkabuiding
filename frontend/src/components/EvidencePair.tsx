import type { Detection } from "../types";

export function EvidencePair({
  sourceUrl,
  vizUrl,
  caption,
  detections,
}: {
  sourceUrl?: string;
  vizUrl?: string;
  caption?: string;
  detections?: Detection[];
}) {
  return (
    <div>
      {caption ? <p className="caption">{caption}</p> : null}
      <div className="pair">
        <div>
          <p className="caption">SOURCE</p>
          {sourceUrl ? <img className="frame" src={sourceUrl} alt="исходное изображение" /> : <p className="empty">нет файла</p>}
        </div>
        <div>
          <p className="caption">AI overlay</p>
          {vizUrl || sourceUrl ? (
            <img className="frame" src={vizUrl || sourceUrl} alt="аннотация" />
          ) : (
            <p className="empty">нет файла</p>
          )}
        </div>
      </div>
      {detections && detections.length > 0 ? (
        <table>
          <thead>
            <tr>
              <th>класс</th>
              <th>confidence</th>
            </tr>
          </thead>
          <tbody>
            {detections.map((item, idx) => (
              <tr key={`${item.class_name}-${idx}`}>
                <td>{item.class_name}</td>
                <td>{item.confidence.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}

const paths: Record<string, string> = {
  overview: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  signal: "M12 3 22 21H2L12 3z M12 9v5 M12 17v.5",
  building: "M4 21V7l8-4 8 4v14 M2 21h20 M9 21v-5h6v5 M8 9h1 M15 9h1 M8 12h1 M15 12h1",
  mark: "M13.2 3.6h2.6 M15.4 4.4C11.4 5.6 10.5 8.6 12.8 10.5 14.6 12 14.8 12.7 12.7 14.4 10.4 16.3 11.3 19.4 15.4 20.5 M13 20.8h2.8",
  arrow: "M5 12h14 M13 6l6 6-6 6",
  expand: "M8 3H3v5 M16 3h5v5 M3 16v5h5 M21 16v5h-5",
  close: "m6 6 12 12 M18 6 6 18",
  image: "M3 3h18v18H3z M3 17l6-6 4 4 3-3 5 5 M16 7h.01",
  user: "M8 7a4 4 0 1 0 8 0 4 4 0 1 0-8 0 M4 21v-2a8 8 0 0 1 16 0v2",
  search: "M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0 M15 15l6 6",
  clock: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0 M12 7v5l3 2",
  plus: "M12 5v14 M5 12h14",
  upload: "M12 16V6 M8 10l4-4 4 4 M5 20h14",
  camera: "M4 8h4l2-2h4l2 2h4v11H4z M12 16a3 3 0 1 0 0-6 3 3 0 0 0 0 6",
  calendar: "M7 4v3 M17 4v3 M4 9h16 M5 6h14v14H5z",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6 M4 12h2 M18 12h2 M6.5 6.5l1.5 1.5 M16 16l1.5 1.5 M6.5 17.5 8 16 M16 8l1.5-1.5",
};
export function Icon({ name }: { name: string }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] || paths.image} /></svg>;
}

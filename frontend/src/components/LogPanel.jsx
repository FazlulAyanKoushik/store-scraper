import { useEffect, useRef } from "react";

export default function LogPanel({ logs }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  return (
    <div
      style={{
        marginTop: 20,
        background: "#1e1e1e",
        color: "#d4d4d4",
        fontFamily: "monospace",
        fontSize: 13,
        padding: 12,
        borderRadius: 6,
        maxHeight: 300,
        overflowY: "auto",
      }}
    >
      {logs.map((msg, i) => (
        <div key={i} style={{ lineHeight: 1.6 }}>
          <span style={{ color: "#888" }}>[{i + 1}]</span>{" "}
          {msg.startsWith("ERROR") || msg.startsWith("WARNING") ? (
            <span style={{ color: "#f48771" }}>{msg}</span>
          ) : (
            msg
          )}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

import { useState } from "react";

export default function SearchForm({ onSearch, loading }) {
  const [storeName, setStoreName] = useState("");

  const handleSubmit = () => {
    if (!storeName.trim()) return;
    onSearch(storeName.trim());
  };

  return (
    <div style={{ display: "flex", gap: 8 }}>
      <input
        value={storeName}
        onChange={(e) => setStoreName(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
        placeholder="e.g. 美匠"
        style={{
          flex: 1,
          padding: "10px 14px",
          fontSize: 18,
          borderRadius: 6,
          border: "1px solid #ccc",
        }}
      />
      <button
        onClick={handleSubmit}
        disabled={loading}
        style={{
          padding: "10px 20px",
          fontSize: 16,
          background: "#0070f3",
          color: "#fff",
          border: "none",
          borderRadius: 6,
          cursor: "pointer",
        }}
      >
        {loading ? "Scraping..." : "Search"}
      </button>
    </div>
  );
}

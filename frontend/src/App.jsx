import { useState, useRef } from "react";
import axios from "axios";
import SearchForm from "./components/SearchForm";
import ResultCard from "./components/ResultCard";
import LogPanel from "./components/LogPanel";

export default function App() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [logs, setLogs] = useState([]);
  const wsRef = useRef(null);

  const handleScrape = async (storeName) => {
    setLoading(true);
    setResult(null);
    setError(null);
    setLogs([]);

    try {
      const res = await axios.post("/api/scrape", { store_name: storeName });
      const { task_id } = res.data;

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const host = window.location.host;
      const ws = new WebSocket(`${protocol}//${host}/api/ws/${task_id}`);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "log") {
          setLogs((prev) => [...prev, data.message]);
        } else if (data.type === "complete") {
          setResult(data.result);
          setLoading(false);
          ws.close();
        } else if (data.type === "error") {
          setError(data.message);
          setLoading(false);
          ws.close();
        }
      };

      ws.onerror = () => {
        setError("WebSocket connection failed.");
        setLoading(false);
      };
    } catch (err) {
      setError(err.response?.data?.detail || "An error occurred.");
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 600, margin: "60px auto", fontFamily: "sans-serif" }}>
      <h1>🏪 Store Product Scraper</h1>
      <p>Enter a store name to count its products listed on Google.</p>

      <SearchForm onSearch={handleScrape} loading={loading} />

      {loading && (
        <p style={{ marginTop: 20 }}>
          ⏳ Scraping in progress... see live logs below.
        </p>
      )}

      {logs.length > 0 && <LogPanel logs={logs} />}

      {error && <p style={{ color: "red", marginTop: 20 }}>❌ {error}</p>}

      {result && <ResultCard result={result} />}
    </div>
  );
}

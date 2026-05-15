export default function ResultCard({ result }) {
  if (!result) return null;

  return (
    <div
      style={{
        marginTop: 30,
        padding: 20,
        border: "1px solid #eee",
        borderRadius: 8,
      }}
    >
      <h2>Results for: {result.store_name}</h2>
      {result.error ? (
        <p style={{ color: "orange" }}>⚠️ {result.error}</p>
      ) : (
        <>
          <p style={{ fontSize: 24 }}>
            📦 <strong>{result.product_count}</strong> products found
          </p>
          {result.products.length > 0 && (
            <ul>
              {result.products.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

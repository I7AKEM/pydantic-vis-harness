import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = {
    ...loadEnv(mode, "..", ""),
    ...loadEnv(mode, ".", ""),
    ...process.env,
  };
  const model =
    env.AVA_MODEL ||
    (env.PYDANTIC_AI_MODEL || "openrouter:anthropic/claude-sonnet-4.6").replace(
      /^openrouter:/,
      "",
    );
  return {
    resolve: { alias: { "csv-parse/sync": "csv-parse/browser/esm/sync" } },
    plugins: [
      react(),
      {
        name: "local-openrouter",
        configureServer(server) {
          server.middlewares.use("/api", async (req, res) => {
            const json = (status, value) => {
              res.statusCode = status;
              res.setHeader("Content-Type", "application/json");
              res.end(JSON.stringify(value));
            };
            if (
              req.headers.origin &&
              req.headers.origin !== `http://${req.headers.host}`
            )
              return json(403, { error: "Origin not allowed" });
            if (req.url === "/config" && req.method === "GET")
              return json(200, {
                model,
                configured: Boolean(env.OPENROUTER_API_KEY),
              });
            if (req.url !== "/llm/chat/completions" || req.method !== "POST")
              return json(404, { error: "Not found" });
            if (!env.OPENROUTER_API_KEY)
              return json(503, {
                error: {
                  message:
                    "Set OPENROUTER_API_KEY in POC/.env or the project .env, then restart npm run dev.",
                },
              });
            try {
              req.setEncoding("utf8");
              let body = "";
              for await (const chunk of req) {
                body += chunk;
                if (Buffer.byteLength(body) > 2 * 1024 * 1024)
                  return json(413, {
                    error: {
                      message:
                        "Analysis request exceeds 2 MB. Use a smaller dataset.",
                    },
                  });
              }
              const payload = JSON.parse(body);
              const upstream = await fetch(
                "https://openrouter.ai/api/v1/chat/completions",
                {
                  method: "POST",
                  headers: {
                    Authorization: `Bearer ${env.OPENROUTER_API_KEY}`,
                    "Content-Type": "application/json",
                  },
                  body: JSON.stringify({ ...payload, model, stream: false }),
                  signal: AbortSignal.timeout(120000),
                },
              );
              res.statusCode = upstream.status;
              res.setHeader("Content-Type", "application/json");
              res.end(await upstream.text());
            } catch (error) {
              json(502, {
                error: { message: `Model request failed: ${error.message}` },
              });
            }
          });
        },
      },
    ],
    optimizeDeps: { include: ["@antv/ava", "@antv/ava/esm/visualization/index.js"] },
    server: { strictPort: true },
    worker: { format: "es" },
  };
});

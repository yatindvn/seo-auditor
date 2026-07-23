import http from "http";
import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import auditRoutes from "./routes/auditRoutes";
import healthRoutes from "./routes/healthRoutes";
import { errorHandler } from "./middleware/errorHandler";
import { wsServer } from "./websocket/wsServer";

dotenv.config();

const app = express();
const PORT = process.env.PORT || 5000;

app.use(cors());
app.use(express.json());

app.use("/api", auditRoutes);
app.use("/api", healthRoutes);

app.use(errorHandler);

const server = http.createServer(app);

wsServer.init(server);

server.listen(PORT, () => {
  console.log(`SEO Auditor Backend Server listening on http://localhost:${PORT}`);
});

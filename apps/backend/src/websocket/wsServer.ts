import { Server as HttpServer } from "http";
import { WebSocketServer, WebSocket } from "ws";
import { WS_EVENTS } from "@seo-auditor/shared";

export class WsServer {
  private wss: WebSocketServer | null = null;

  public init(server: HttpServer) {
    this.wss = new WebSocketServer({ server });

    this.wss.on("connection", (ws: WebSocket) => {
      ws.send(JSON.stringify({ event: WS_EVENTS.CONNECT, message: "Connected to SEO Auditor Live Stream Server" }));

      ws.on("message", (message: string) => {
        try {
          const data = JSON.parse(message.toString());
          if (data.event === "ping") {
            ws.send(JSON.stringify({ event: "pong", timestamp: Date.now() }));
          }
        } catch {
          // Ignore invalid frames
        }
      });
    });
  }

  public broadcast(event: string, payload: any) {
    if (!this.wss) return;
    const message = JSON.stringify({ event, payload });
    this.wss.clients.forEach((client) => {
      if (client.readyState === WebSocket.OPEN) {
        client.send(message);
      }
    });
  }

  public emitPageCrawled(pageData: any) {
    this.broadcast(WS_EVENTS.PAGE_CRAWLED, pageData);
    this.broadcast(WS_EVENTS.ACTIVITY_NEW, {
      id: `act_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
      type: "page_crawled",
      message: `Crawled ${pageData.url} (Status: ${pageData.status || 200}, Depth: ${pageData.depth})`,
      timestamp: new Date().toISOString(),
      url: pageData.url,
    });
  }

  public emitLinkFound(source: string, target: string, external: boolean) {
    this.broadcast(WS_EVENTS.LINK_FOUND, { source, target, external });
  }

  public emitIssueDetected(issue: any) {
    this.broadcast(WS_EVENTS.ISSUE_DETECTED, issue);
  }
}

export const wsServer = new WsServer();
